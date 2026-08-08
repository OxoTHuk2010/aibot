"""Предоставляет чтение и ручную публикацию Telegram-постов через HTTP.

Router выбирает publisher по настройкам и преобразует доменные и интеграционные
ошибки в HTTP; транзакции и защита от повторной отправки остаются в сервисе.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import PostStatus
from app.publisher.factory import Publisher, create_publisher
from app.publisher.telegram import (
    TelegramPublisherConfigurationError,
    TelegramPublishError,
)
from app.schemas import PostResponse
from app.services.post_service import (
    PostAlreadyPublishedError,
    PostNotFoundError,
    PostNotPublishableError,
    get_post,
    list_posts,
    publish_post,
)

router = APIRouter(prefix="/posts", tags=["Posts"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_publisher() -> Publisher:
    """Создаёт publisher, выбранный настройками приложения."""
    return create_publisher(settings)


PublisherDependency = Annotated[Publisher, Depends(get_publisher)]


def _not_found() -> HTTPException:
    """Создаёт единый HTTP-ответ для отсутствующего поста."""
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")


@router.get(
    "",
    response_model=list[PostResponse],
    summary="Получить список постов",
    description="Возвращает посты с SQL-фильтрацией по статусу и offset-пагинацией.",
    response_description="Упорядоченный список сгенерированных постов.",
    responses={422: {"description": "Фильтр или параметр пагинации недопустим."}},
)
async def list_all(
    session: SessionDependency,
    post_status: Annotated[
        PostStatus | None,
        Query(alias="status", description="Оставить посты только указанного статуса."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Число записей в ответе, от 1 до 100."),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Число записей, пропускаемых от начала выборки."),
    ] = 0,
) -> list[PostResponse]:
    """Возвращает страницу постов по необязательному SQL-фильтру статуса."""
    posts = await list_posts(
        session,
        status=post_status,
        limit=limit,
        offset=offset,
    )
    return [PostResponse.from_post(post) for post in posts]


@router.get(
    "/{post_id}",
    response_model=PostResponse,
    summary="Получить пост",
    description="Возвращает пост вместе с идентификаторами связанных новостей.",
    response_description="Найденный пост.",
    responses={
        404: {"description": "Пост не найден."},
        422: {"description": "Идентификатор поста имеет неверный формат."},
    },
)
async def get_one(
    post_id: Annotated[int, Path(description="Идентификатор поста.")],
    session: SessionDependency,
) -> PostResponse:
    """Возвращает один пост или HTTP 404 при его отсутствии."""
    try:
        post = await get_post(session, post_id)
    except PostNotFoundError as error:
        raise _not_found() from error
    return PostResponse.from_post(post)


@router.post(
    "/{post_id}/publish",
    response_model=PostResponse,
    summary="Опубликовать пост в Telegram",
    description=(
        "Отправляет generated-пост через выбранный Telegram publisher и сохраняет "
        "message ID. Уже опубликованный или непригодный пост повторно не отправляется."
    ),
    response_description="Пост с результатом успешной публикации.",
    responses={
        404: {"description": "Пост не найден."},
        409: {"description": "Пост уже опубликован или не готов к публикации."},
        422: {"description": "Идентификатор поста имеет неверный формат."},
        502: {"description": "Telegram отклонил сообщение или не ответил."},
        503: {"description": "Выбранный Telegram publisher не настроен."},
    },
)
async def publish(
    post_id: Annotated[int, Path(description="Идентификатор публикуемого поста.")],
    session: SessionDependency,
    publisher: PublisherDependency,
) -> PostResponse:
    """Публикует один пост и возвращает сохранённый результат.

    Операция имеет внешний побочный эффект. Сервис блокирует строку Post и
    предотвращает повторный вызов publisher для уже опубликованной записи.
    """
    try:
        post = await publish_post(session, post_id, publisher)
    except PostNotFoundError as error:
        raise _not_found() from error
    except PostAlreadyPublishedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Post is already published",
        ) from error
    except PostNotPublishableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Post is not publishable",
        ) from error
    except TelegramPublisherConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram publication is not configured",
        ) from error
    except TelegramPublishError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Telegram publication failed",
        ) from error
    return PostResponse.from_post(post)
