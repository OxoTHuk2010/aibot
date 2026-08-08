"""Отображает управление ключевыми словами в HTTP API.

Router передаёт операции сервисному слою и преобразует доменные ошибки в
стабильные HTTP-ответы, не выполняя SQL самостоятельно.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import KeywordType
from app.schemas import KeywordCreate, KeywordResponse, KeywordUpdate
from app.services.keyword_service import (
    KeywordAlreadyExistsError,
    KeywordNotFoundError,
    create_keyword,
    disable_keyword,
    get_keyword,
    list_keywords,
    update_keyword,
)

router = APIRouter(prefix="/keywords", tags=["Keywords"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def not_found() -> HTTPException:
    """Создаёт единый HTTP-ответ для отсутствующего ключевого слова."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")


def conflict() -> HTTPException:
    """Создаёт единый HTTP-ответ для конфликта нормализованного слова."""
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Keyword already exists",
    )


@router.post(
    "",
    response_model=KeywordResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Создать ключевое слово",
    description="Нормализует и сохраняет уникальное правило фильтрации новостей.",
    response_description="Созданное правило фильтрации.",
    responses={
        409: {"description": "Такое нормализованное слово уже существует."},
        422: {"description": "Тело запроса не прошло валидацию."},
    },
)
async def create(data: KeywordCreate, session: SessionDependency) -> KeywordResponse:
    """Создаёт правило и отображает конфликт уникальности в HTTP 409."""
    try:
        keyword = await create_keyword(session, data)
    except KeywordAlreadyExistsError as error:
        raise conflict() from error
    return KeywordResponse.model_validate(keyword)


@router.get(
    "",
    response_model=list[KeywordResponse],
    summary="Получить список ключевых слов",
    description="Возвращает правила с SQL-фильтрацией и offset-пагинацией.",
    response_description="Упорядоченный список правил фильтрации.",
    responses={422: {"description": "Фильтр или параметр пагинации недопустим."}},
)
async def list_all(
    session: SessionDependency,
    keyword_type: Annotated[
        KeywordType | None,
        Query(alias="type", description="Оставить только include- или exclude-правила."),
    ] = None,
    enabled: Annotated[
        bool | None,
        Query(description="Оставить только включённые или отключённые правила."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Число записей в ответе, от 1 до 100."),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Число записей, пропускаемых от начала выборки."),
    ] = 0,
) -> list[KeywordResponse]:
    """Возвращает страницу ключевых слов по необязательным SQL-фильтрам."""
    keywords = await list_keywords(
        session,
        keyword_type=keyword_type,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )
    return [KeywordResponse.model_validate(keyword) for keyword in keywords]


@router.get(
    "/{keyword_id}",
    response_model=KeywordResponse,
    summary="Получить ключевое слово",
    description="Возвращает правило независимо от его признака enabled.",
    response_description="Найденное правило фильтрации.",
    responses={
        404: {"description": "Ключевое слово не найдено."},
        422: {"description": "Идентификатор имеет неверный формат."},
    },
)
async def get_one(
    keyword_id: Annotated[int, Path(description="Идентификатор ключевого слова.")],
    session: SessionDependency,
) -> KeywordResponse:
    """Возвращает одно правило или HTTP 404 при его отсутствии."""
    try:
        keyword = await get_keyword(session, keyword_id)
    except KeywordNotFoundError as error:
        raise not_found() from error
    return KeywordResponse.model_validate(keyword)


@router.patch(
    "/{keyword_id}",
    response_model=KeywordResponse,
    summary="Изменить ключевое слово",
    description="Частично обновляет правило; явные null и пустой PATCH запрещены.",
    response_description="Обновлённое правило фильтрации.",
    responses={
        404: {"description": "Ключевое слово не найдено."},
        409: {"description": "Такое нормализованное слово уже существует."},
        422: {"description": "Путь или тело запроса не прошли валидацию."},
    },
)
async def update(
    keyword_id: Annotated[int, Path(description="Идентификатор изменяемого правила.")],
    data: KeywordUpdate,
    session: SessionDependency,
) -> KeywordResponse:
    """Обновляет переданные поля правила и отображает доменные ошибки в HTTP."""
    try:
        keyword = await update_keyword(session, keyword_id, data)
    except KeywordNotFoundError as error:
        raise not_found() from error
    except KeywordAlreadyExistsError as error:
        raise conflict() from error
    return KeywordResponse.model_validate(keyword)


@router.delete(
    "/{keyword_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Отключить ключевое слово",
    description="Идемпотентно устанавливает enabled=false без физического удаления правила.",
    responses={
        404: {"description": "Ключевое слово не найдено."},
        422: {"description": "Идентификатор имеет неверный формат."},
    },
)
async def disable(
    keyword_id: Annotated[int, Path(description="Идентификатор отключаемого правила.")],
    session: SessionDependency,
) -> Response:
    """Мягко отключает правило; повторный вызов остаётся успешным."""
    try:
        await disable_keyword(session, keyword_id)
    except KeywordNotFoundError as error:
        raise not_found() from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
