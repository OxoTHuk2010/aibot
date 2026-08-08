"""Оркестрирует ingestion, дедупликацию и чтение новостей.

Сервис отделяет parser layer от PostgreSQL: нормализует элементы, вычисляет
SHA-256, применяет фильтры и владеет транзакцией одного запуска источника.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Keyword, NewsItem, NewsItemStatus
from app.parser.base import NewsParser, ParsedNewsItem, create_parser
from app.schemas import ParseSourceResponse
from app.services.filter_service import determine_news_status
from app.services.source_service import get_source
from app.utils.hashing import content_hash, normalize_url


class SourceDisabledError(Exception):
    """Сообщает, что отключённый источник нельзя разбирать вручную."""


class NewsItemNotFoundError(Exception):
    """Сообщает, что запрошенная новость не существует."""


async def parse_source(
    session: AsyncSession,
    source_id: int,
    *,
    parser: NewsParser | None = None,
) -> ParseSourceResponse:
    """Получает, фильтрует и сохраняет новости одного источника.

    Каждая вставка использует savepoint: конфликт ``content_hash`` увеличивает
    счётчик дублей и не откатывает остальные элементы. ``last_parsed_at`` и все
    успешные записи фиксируются одной итоговой транзакцией после ответа parser.
    """
    source = await get_source(session, source_id)
    if not source.enabled:
        raise SourceDisabledError

    selected_parser = parser or create_parser(source.source_type, settings)
    parsed_items = await selected_parser.parse(source)
    keywords = list(
        (await session.scalars(select(Keyword).where(Keyword.enabled.is_(True)))).all()
    )

    created = 0
    duplicates = 0
    filtered = 0
    errors = 0
    for parsed_item in parsed_items:
        try:
            normalized = _normalize_item(parsed_item)
            status = determine_news_status(normalized, keywords)
            news_item = NewsItem(
                source_id=source.id,
                external_id=normalized.external_id,
                title=normalized.title,
                url=normalized.url,
                summary=normalized.summary,
                raw_text=normalized.raw_text,
                published_at=normalized.published_at,
                content_hash=content_hash(
                    title=normalized.title,
                    url=normalized.url,
                    raw_text=normalized.raw_text,
                    published_at=normalized.published_at,
                ),
                status=status,
            )
            try:
                async with session.begin_nested():
                    session.add(news_item)
                    await session.flush()
            except IntegrityError as error:
                if _is_unique_violation(error):
                    duplicates += 1
                else:
                    errors += 1
                continue
            created += 1
            if status == NewsItemStatus.FILTERED:
                filtered += 1
        except (TypeError, ValueError):
            errors += 1

    source.last_parsed_at = datetime.now(UTC)
    await session.commit()
    return ParseSourceResponse(
        source_id=source.id,
        found=len(parsed_items),
        created=created,
        duplicates=duplicates,
        filtered=filtered,
        errors=errors,
    )


async def get_news_item(session: AsyncSession, news_id: int) -> NewsItem:
    """Возвращает NewsItem по ID или выбрасывает ``NewsItemNotFoundError``."""
    news_item = await session.get(NewsItem, news_id)
    if news_item is None:
        raise NewsItemNotFoundError
    return news_item


async def list_news_items(
    session: AsyncSession,
    *,
    source_id: int | None = None,
    status: NewsItemStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[NewsItem]:
    """Возвращает страницу новостей с SQL-фильтрами источника и статуса.

    Сначала идут наиболее свежие опубликованные новости, затем записи без даты в
    стабильном порядке времени создания и ID.
    """
    statement = select(NewsItem)
    if source_id is not None:
        statement = statement.where(NewsItem.source_id == source_id)
    if status is not None:
        statement = statement.where(NewsItem.status == status)
    statement = statement.order_by(
        NewsItem.published_at.desc().nulls_last(),
        NewsItem.created_at.desc(),
        NewsItem.id.desc(),
    )
    statement = statement.limit(limit).offset(offset)
    return list((await session.scalars(statement)).all())


async def list_eligible_news_items(
    session: AsyncSession,
    *,
    limit: int,
) -> list[NewsItem]:
    """Выбирает неиспользованные new-новости в детерминированном FIFO-порядке.

    SQL исключает NewsItem с любой M:N-связью Post и применяет обязательный
    положительный лимит до загрузки данных.
    """
    if limit < 1:
        raise ValueError("limit must be at least 1")
    statement = (
        select(NewsItem)
        .where(
            NewsItem.status == NewsItemStatus.NEW,
            ~NewsItem.posts.any(),
        )
        .order_by(
            NewsItem.published_at.asc().nulls_last(),
            NewsItem.created_at.asc(),
            NewsItem.id.asc(),
        )
        .limit(limit)
    )
    return list((await session.scalars(statement)).all())


def _normalize_item(item: ParsedNewsItem) -> ParsedNewsItem:
    """Приводит parser-результат к ограничениям ORM перед сохранением.

    Заголовок обязателен, URL и external ID ограничены длиной, а naive datetime
    трактуется как UTC. Нарушение контракта элемента приводит к ``ValueError``.
    """
    title = " ".join(item.title.split())[:200]
    if not title:
        raise ValueError("news title must not be blank")
    url = normalize_url(item.url) if item.url else None
    if url and len(url) > 500:
        raise ValueError("news URL exceeds ORM limit")
    external_id = _optional_text(item.external_id)
    if external_id and len(external_id) > 255:
        raise ValueError("external id exceeds ORM limit")
    published_at = item.published_at
    if published_at is not None and published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=UTC)
    return ParsedNewsItem(
        title=title,
        url=url,
        summary=_optional_text(item.summary),
        raw_text=_optional_text(item.raw_text),
        published_at=published_at,
        external_id=external_id,
    )


def _optional_text(value: str | None) -> str | None:
    """Удаляет внешние пробелы и заменяет пустой необязательный текст на ``None``."""
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _is_unique_violation(error: IntegrityError) -> bool:
    """Определяет PostgreSQL unique violation по SQLSTATE 23505."""
    sqlstate = getattr(error.orig, "sqlstate", None)
    if sqlstate is None:
        sqlstate = getattr(getattr(error.orig, "__cause__", None), "sqlstate", None)
    return sqlstate == "23505"
