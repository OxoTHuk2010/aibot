"""Реализует сервисные операции управления источниками новостей.

Модуль владеет SQL и транзакционными границами мутаций Source, но не зависит от
HTTPException. Уникальность URL окончательно обеспечивает PostgreSQL.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Source, SourceType
from app.schemas import SourceCreate, SourceUpdate


class SourceNotFoundError(Exception):
    """Сообщает, что запрошенный источник не существует."""


class SourceAlreadyExistsError(Exception):
    """Сообщает о конфликте уникального URL источника."""


async def create_source(session: AsyncSession, data: SourceCreate) -> Source:
    """Создаёт источник и фиксирует его в PostgreSQL.

    При конфликте URL транзакция откатывается, а ``IntegrityError`` преобразуется
    в ``SourceAlreadyExistsError`` для независимого от HTTP сервисного контракта.
    """
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
    """Возвращает Source по ID или выбрасывает ``SourceNotFoundError``."""
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
    """Возвращает страницу источников с SQL-фильтрами типа и enabled.

    Сортировка по времени создания и ID обеспечивает стабильный порядок выборки.
    """
    statement = select(Source)
    if source_type is not None:
        statement = statement.where(Source.source_type == source_type)
    if enabled is not None:
        statement = statement.where(Source.enabled.is_(enabled))
    statement = statement.order_by(Source.created_at.desc(), Source.id.desc())
    statement = statement.limit(limit).offset(offset)
    return list((await session.scalars(statement)).all())


async def list_enabled_sources(session: AsyncSession) -> list[Source]:
    """Возвращает все включённые источники в стабильном порядке для pipeline."""
    statement = (
        select(Source)
        .where(Source.enabled.is_(True))
        .order_by(Source.created_at.asc(), Source.id.asc())
    )
    return list((await session.scalars(statement)).all())


async def update_source(
    session: AsyncSession,
    source_id: int,
    data: SourceUpdate,
) -> Source:
    """Частично обновляет источник и фиксирует транзакцию.

    URL преобразуется из Pydantic-типа в строку. Конфликт уникальности откатывает
    все изменения и становится ``SourceAlreadyExistsError``.
    """
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
    """Идемпотентно отключает Source без физического удаления и фиксирует изменение."""
    source = await get_source(session, source_id)
    source.enabled = False
    await session.commit()
