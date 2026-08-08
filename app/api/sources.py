"""Отображает операции с источниками и ручным сбором новостей в HTTP API.

Модуль не содержит SQL: он проверяет HTTP-параметры, вызывает сервисный слой и
преобразует доменные ошибки в стабильные ответы клиента.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import SourceType
from app.parser.base import (
    ParserConfigurationError,
    ParserError,
    UnsupportedSourceTypeError,
)
from app.schemas import ParseSourceResponse, SourceCreate, SourceResponse, SourceUpdate
from app.services.news_service import SourceDisabledError, parse_source
from app.services.source_service import (
    SourceAlreadyExistsError,
    SourceNotFoundError,
    create_source,
    disable_source,
    get_source,
    list_sources,
    update_source,
)

router = APIRouter(prefix="/sources", tags=["Sources"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def not_found() -> HTTPException:
    """Создаёт единый HTTP-ответ для отсутствующего источника."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")


def conflict() -> HTTPException:
    """Создаёт единый HTTP-ответ для конфликта уникального URL."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Source URL already exists",
    )


@router.post(
    "/{source_id}/parse",
    response_model=ParseSourceResponse,
    summary="Собрать новости из источника",
    description=(
        "Запускает выбранный parser синхронно с HTTP-запросом, сохраняет новые "
        "NewsItem и возвращает счётчики обработки. Отключённый источник не разбирается."
    ),
    response_description="Счётчики завершённого разбора источника.",
    responses={
        400: {"description": "Тип источника не поддерживается."},
        404: {"description": "Источник не найден."},
        409: {"description": "Источник отключён или parser не настроен."},
        422: {"description": "Идентификатор источника имеет неверный формат."},
        502: {"description": "Внешний источник недоступен или содержит некорректные данные."},
    },
)
async def parse(
    source_id: Annotated[int, Path(description="Идентификатор источника для разбора.")],
    session: SessionDependency,
) -> ParseSourceResponse:
    """Запускает сбор одного включённого источника и возвращает его итог.

    Ошибки источника или конфигурации преобразуются в HTTP-ответы без раскрытия
    внутренних деталей parser и credentials.
    """
    try:
        return await parse_source(session, source_id)
    except SourceNotFoundError as error:
        raise not_found() from error
    except SourceDisabledError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source is disabled",
        ) from error
    except ParserConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Source parser is not configured",
        ) from error
    except UnsupportedSourceTypeError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported source type",
        ) from error
    except ParserError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Source fetch or parsing failed",
        ) from error


@router.post(
    "",
    response_model=SourceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать источник",
    description="Сохраняет новый RSS, HTML или Telegram-источник с уникальным URL.",
    response_description="Созданный источник.",
    responses={
        409: {"description": "Источник с таким URL уже существует."},
        422: {"description": "Тело запроса не прошло валидацию."},
    },
)
async def create(data: SourceCreate, session: SessionDependency) -> SourceResponse:
    """Создаёт источник и отображает конфликт уникальности в HTTP 409."""
    try:
        source = await create_source(session, data)
    except SourceAlreadyExistsError as error:
        raise conflict() from error
    return SourceResponse.model_validate(source)


@router.get(
    "",
    response_model=list[SourceResponse],
    summary="Получить список источников",
    description="Возвращает источники с SQL-фильтрацией и offset-пагинацией.",
    response_description="Упорядоченный список источников.",
    responses={422: {"description": "Фильтр или параметр пагинации недопустим."}},
)
async def list_all(
    session: SessionDependency,
    source_type: Annotated[
        SourceType | None,
        Query(description="Оставить источники только указанного типа."),
    ] = None,
    enabled: Annotated[
        bool | None,
        Query(description="Оставить только включённые или отключённые источники."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Число записей в ответе, от 1 до 100."),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Число записей, пропускаемых от начала выборки."),
    ] = 0,
) -> list[SourceResponse]:
    """Возвращает страницу источников по необязательным SQL-фильтрам."""
    sources = await list_sources(
        session,
        source_type=source_type,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )
    return [SourceResponse.model_validate(source) for source in sources]


@router.get(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Получить источник",
    description="Возвращает источник независимо от его признака enabled.",
    response_description="Найденный источник.",
    responses={
        404: {"description": "Источник не найден."},
        422: {"description": "Идентификатор источника имеет неверный формат."},
    },
)
async def get_one(
    source_id: Annotated[int, Path(description="Идентификатор источника.")],
    session: SessionDependency,
) -> SourceResponse:
    """Возвращает один источник или HTTP 404 при его отсутствии."""
    try:
        source = await get_source(session, source_id)
    except SourceNotFoundError as error:
        raise not_found() from error
    return SourceResponse.model_validate(source)


@router.patch(
    "/{source_id}",
    response_model=SourceResponse,
    summary="Изменить источник",
    description="Частично обновляет источник; явные null и пустой PATCH запрещены.",
    response_description="Обновлённый источник.",
    responses={
        404: {"description": "Источник не найден."},
        409: {"description": "Другой источник уже использует указанный URL."},
        422: {"description": "Путь или тело запроса не прошли валидацию."},
    },
)
async def update(
    source_id: Annotated[int, Path(description="Идентификатор изменяемого источника.")],
    data: SourceUpdate,
    session: SessionDependency,
) -> SourceResponse:
    """Обновляет переданные поля источника и отображает доменные ошибки в HTTP."""
    try:
        source = await update_source(session, source_id, data)
    except SourceNotFoundError as error:
        raise not_found() from error
    except SourceAlreadyExistsError as error:
        raise conflict() from error
    return SourceResponse.model_validate(source)


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отключить источник",
    description=(
        "Идемпотентно устанавливает enabled=false без физического удаления записи "
        "и связанных новостей."
    ),
    responses={
        404: {"description": "Источник не найден."},
        422: {"description": "Идентификатор источника имеет неверный формат."},
    },
)
async def disable(
    source_id: Annotated[int, Path(description="Идентификатор отключаемого источника.")],
    session: SessionDependency,
) -> Response:
    """Мягко отключает источник; повторный вызов остаётся успешным."""
    try:
        await disable_source(session, source_id)
    except SourceNotFoundError as error:
        raise not_found() from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
