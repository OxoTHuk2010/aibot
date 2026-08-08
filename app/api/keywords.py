from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
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
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Keyword not found")


def conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Keyword already exists",
    )


@router.post("", response_model=KeywordResponse, status_code=status.HTTP_201_CREATED)
async def create(data: KeywordCreate, session: SessionDependency) -> KeywordResponse:
    try:
        keyword = await create_keyword(session, data)
    except KeywordAlreadyExistsError as error:
        raise conflict() from error
    return KeywordResponse.model_validate(keyword)


@router.get("", response_model=list[KeywordResponse])
async def list_all(
    session: SessionDependency,
    keyword_type: Annotated[KeywordType | None, Query(alias="type")] = None,
    enabled: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[KeywordResponse]:
    keywords = await list_keywords(
        session,
        keyword_type=keyword_type,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )
    return [KeywordResponse.model_validate(keyword) for keyword in keywords]


@router.get("/{keyword_id}", response_model=KeywordResponse)
async def get_one(keyword_id: int, session: SessionDependency) -> KeywordResponse:
    try:
        keyword = await get_keyword(session, keyword_id)
    except KeywordNotFoundError as error:
        raise not_found() from error
    return KeywordResponse.model_validate(keyword)


@router.patch("/{keyword_id}", response_model=KeywordResponse)
async def update(
    keyword_id: int,
    data: KeywordUpdate,
    session: SessionDependency,
) -> KeywordResponse:
    try:
        keyword = await update_keyword(session, keyword_id, data)
    except KeywordNotFoundError as error:
        raise not_found() from error
    except KeywordAlreadyExistsError as error:
        raise conflict() from error
    return KeywordResponse.model_validate(keyword)


@router.delete("/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disable(keyword_id: int, session: SessionDependency) -> Response:
    try:
        await disable_keyword(session, keyword_id)
    except KeywordNotFoundError as error:
        raise not_found() from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
