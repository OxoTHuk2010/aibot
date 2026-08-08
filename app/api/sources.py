from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_session
from app.models import SourceType
from app.schemas import SourceCreate, SourceResponse, SourceUpdate
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
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")


def conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Source URL already exists",
    )


@router.post("", response_model=SourceResponse, status_code=status.HTTP_201_CREATED)
async def create(data: SourceCreate, session: SessionDependency) -> SourceResponse:
    try:
        source = await create_source(session, data)
    except SourceAlreadyExistsError as error:
        raise conflict() from error
    return SourceResponse.model_validate(source)


@router.get("", response_model=list[SourceResponse])
async def list_all(
    session: SessionDependency,
    source_type: SourceType | None = None,
    enabled: bool | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[SourceResponse]:
    sources = await list_sources(
        session,
        source_type=source_type,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )
    return [SourceResponse.model_validate(source) for source in sources]


@router.get("/{source_id}", response_model=SourceResponse)
async def get_one(source_id: int, session: SessionDependency) -> SourceResponse:
    try:
        source = await get_source(session, source_id)
    except SourceNotFoundError as error:
        raise not_found() from error
    return SourceResponse.model_validate(source)


@router.patch("/{source_id}", response_model=SourceResponse)
async def update(
    source_id: int,
    data: SourceUpdate,
    session: SessionDependency,
) -> SourceResponse:
    try:
        source = await update_source(session, source_id, data)
    except SourceNotFoundError as error:
        raise not_found() from error
    except SourceAlreadyExistsError as error:
        raise conflict() from error
    return SourceResponse.model_validate(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disable(source_id: int, session: SessionDependency) -> Response:
    try:
        await disable_source(session, source_id)
    except SourceNotFoundError as error:
        raise not_found() from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
