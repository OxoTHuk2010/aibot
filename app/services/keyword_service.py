"""Реализует сервисные операции управления правилами фильтрации.

Модуль владеет SQL и транзакциями мутаций Keyword и не зависит от HTTP-слоя.
Уникальность нормализованного слова окончательно обеспечивает PostgreSQL.
"""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Keyword, KeywordType
from app.schemas import KeywordCreate, KeywordUpdate


class KeywordNotFoundError(Exception):
    """Сообщает, что запрошенное ключевое слово не существует."""


class KeywordAlreadyExistsError(Exception):
    """Сообщает о конфликте уникального нормализованного слова."""


async def create_keyword(session: AsyncSession, data: KeywordCreate) -> Keyword:
    """Создаёт правило фильтрации и фиксирует его в PostgreSQL.

    При конфликте слова транзакция откатывается, а ``IntegrityError`` становится
    ``KeywordAlreadyExistsError``.
    """
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
    """Возвращает Keyword по ID или выбрасывает ``KeywordNotFoundError``."""
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
    """Возвращает страницу правил с SQL-фильтрами типа и enabled.

    Сортировка по времени создания и ID обеспечивает стабильный порядок выборки.
    """
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
    """Частично обновляет правило фильтрации и фиксирует транзакцию.

    Конфликт нормализованного слова откатывает изменения и преобразуется в
    ``KeywordAlreadyExistsError``.
    """
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
    """Идемпотентно отключает Keyword без физического удаления и фиксирует изменение."""
    keyword = await get_keyword(session, keyword_id)
    keyword.enabled = False
    await session.commit()
