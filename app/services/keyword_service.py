from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Keyword, KeywordType
from app.schemas import KeywordCreate, KeywordUpdate


class KeywordNotFoundError(Exception):
    """The requested keyword does not exist."""


class KeywordAlreadyExistsError(Exception):
    """A keyword with the same normalized word already exists."""


async def create_keyword(session: AsyncSession, data: KeywordCreate) -> Keyword:
    keyword = Keyword(word=data.word, type=data.type, enabled=data.enabled)
    session.add(keyword)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise KeywordAlreadyExistsError from error
    await session.refresh(keyword)
    return keyword


async def get_keyword(session: AsyncSession, keyword_id: int) -> Keyword:
    keyword = await session.get(Keyword, keyword_id)
    if keyword is None:
        raise KeywordNotFoundError
    return keyword


async def list_keywords(
    session: AsyncSession,
    *,
    keyword_type: KeywordType | None = None,
    enabled: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Keyword]:
    statement = select(Keyword)
    if keyword_type is not None:
        statement = statement.where(Keyword.type == keyword_type)
    if enabled is not None:
        statement = statement.where(Keyword.enabled.is_(enabled))
    statement = statement.order_by(Keyword.created_at.desc(), Keyword.id.desc())
    statement = statement.limit(limit).offset(offset)
    return list((await session.scalars(statement)).all())


async def update_keyword(
    session: AsyncSession,
    keyword_id: int,
    data: KeywordUpdate,
) -> Keyword:
    keyword = await get_keyword(session, keyword_id)
    for field_name, value in data.model_dump(exclude_unset=True).items():
        setattr(keyword, field_name, value)
    try:
        await session.commit()
    except IntegrityError as error:
        await session.rollback()
        raise KeywordAlreadyExistsError from error
    await session.refresh(keyword)
    return keyword


async def disable_keyword(session: AsyncSession, keyword_id: int) -> None:
    keyword = await get_keyword(session, keyword_id)
    keyword.enabled = False
    await session.commit()
