"""Предоставляет read-only HTTP API собранных новостей.

Router описывает фильтры и пагинацию, а все SQL-запросы выполняет сервисный слой.
Создание новостей доступно только через разбор источников.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import NewsItemStatus
from app.schemas import NewsItemResponse
from app.services.news_service import NewsItemNotFoundError, get_news_item, list_news_items

router = APIRouter(prefix="/news", tags=["News"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.get(
    "",
    response_model=list[NewsItemResponse],
    summary="Получить список новостей",
    description="Возвращает новости с SQL-фильтрацией и offset-пагинацией.",
    response_description="Упорядоченный список нормализованных новостей.",
    responses={422: {"description": "Фильтр или параметр пагинации недопустим."}},
)
async def list_all(
    session: SessionDependency,
    source_id: Annotated[
        int | None,
        Query(description="Оставить новости только указанного источника."),
    ] = None,
    news_status: Annotated[
        NewsItemStatus | None,
        Query(alias="status", description="Оставить новости только указанного статуса."),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=100, description="Число записей в ответе, от 1 до 100."),
    ] = 50,
    offset: Annotated[
        int,
        Query(ge=0, description="Число записей, пропускаемых от начала выборки."),
    ] = 0,
) -> list[NewsItemResponse]:
    """Возвращает страницу новостей по необязательным SQL-фильтрам."""
    news_items = await list_news_items(
        session,
        source_id=source_id,
        status=news_status,
        limit=limit,
        offset=offset,
    )
    return [NewsItemResponse.model_validate(item) for item in news_items]


@router.get(
    "/{news_id}",
    response_model=NewsItemResponse,
    summary="Получить новость",
    description="Возвращает нормализованную новость с результатом фильтрации.",
    response_description="Найденная новость.",
    responses={
        404: {"description": "Новость не найдена."},
        422: {"description": "Идентификатор новости имеет неверный формат."},
    },
)
async def get_one(
    news_id: Annotated[int, Path(description="Идентификатор новости.")],
    session: SessionDependency,
) -> NewsItemResponse:
    """Возвращает одну новость или HTTP 404 при её отсутствии."""
    try:
        news_item = await get_news_item(session, news_id)
    except NewsItemNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="News item not found",
        ) from error
    return NewsItemResponse.model_validate(news_item)
