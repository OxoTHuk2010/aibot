from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source, SourceType
from app.schemas import SourceCreate, SourceUpdate


class SourceNotFoundError(Exception):
    """The requested source does not exist."""


class SourceAlreadyExistsError(Exception):
    """A source with the same URL already exists."""


async def create_source(session: AsyncSession, data: SourceCreate) -> Source:
    source = Source(
        name=data.name,
        source_type=data.source_type,
        url=str(data.url),
        enabled=data.enabled,
    )
    session.add(source)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise SourceAlreadyExistsError from error
    await session.refresh(source)
    return source


async def get_source(session: AsyncSession, source_id: int) -> Source:
    source = await session.get(Source, source_id)
    if source is None:
        raise SourceNotFoundError
    return source


async def list_sources(
    session: AsyncSession,
    *,
    source_type: SourceType | None = None,
    enabled: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Source]:
    statement = select(Source)
    if source_type is not None:
        statement = statement.where(Source.source_type == source_type)
    if enabled is not None:
        statement = statement.where(Source.enabled.is_(enabled))
    statement = statement.order_by(Source.created_at.desc(), Source.id.desc())
    statement = statement.limit(limit).offset(offset)
    return list((await session.scalars(statement)).all())


async def update_source(
    session: AsyncSession,
    source_id: int,
    data: SourceUpdate,
) -> Source:
    source = await get_source(session, source_id)
    values = data.model_dump(exclude_unset=True)
    if "url" in values:
        values["url"] = str(values["url"])
    for field_name, value in values.items():
        setattr(source, field_name, value)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise SourceAlreadyExistsError from error
    await session.refresh(source)
    return source


async def disable_source(session: AsyncSession, source_id: int) -> None:
    source = await get_source(session, source_id)
    source.enabled = False
    await session.commit()
