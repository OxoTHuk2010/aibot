from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import NewsItemStatus
from app.schemas import NewsItemResponse
from app.services.news_service import NewsItemNotFoundError, get_news_item, list_news_items

router = APIRouter(prefix="/news", tags=["News"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=list[NewsItemResponse])
async def list_all(
    session: SessionDependency,
    source_id: int | None = None,
    news_status: Annotated[NewsItemStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[NewsItemResponse]:
    news_items = await list_news_items(
        session,
        source_id=source_id,
        status=news_status,
        limit=limit,
        offset=offset,
    )
    return [NewsItemResponse.model_validate(item) for item in news_items]


@router.get("/{news_id}", response_model=NewsItemResponse)
async def get_one(news_id: int, session: SessionDependency) -> NewsItemResponse:
    try:
        news_item = await get_news_item(session, news_id)
    except NewsItemNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="News item not found",
        ) from error
    return NewsItemResponse.model_validate(news_item)
