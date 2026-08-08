import asyncio
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.models import NewsItem, NewsItemStatus, Post, PostStatus, Source, SourceType
from app.services.news_service import list_eligible_news_items
from app.services.source_service import list_enabled_sources

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def migrated_pipeline_database(database_url: str) -> Iterator[str]:
    # Earlier config unit tests intentionally import Settings with a fake localhost URL.
    # Alembic must resolve the current integration DATABASE_URL instead of that cached module.
    for name in ("app.models", "app.database", "app.config"):
        sys.modules.pop(name, None)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(config, "head")
    yield database_url
    command.downgrade(config, "base")

    async def drop_version_table() -> None:
        engine = create_async_engine(database_url)
        try:
            async with engine.begin() as connection:
                await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        finally:
            await engine.dispose()

    asyncio.run(drop_version_table())


@pytest.fixture
async def session(
    migrated_pipeline_database: str,
) -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(migrated_pipeline_database)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as database_session:
        await database_session.execute(delete(Post))
        await database_session.execute(delete(NewsItem))
        await database_session.execute(delete(Source))
        await database_session.commit()
        yield database_session
        await database_session.rollback()
    await engine.dispose()


@pytest.mark.asyncio
async def test_enabled_source_selection_is_sql_filtered_and_stable(
    session: AsyncSession,
) -> None:
    session.add_all(
        [
            Source(name="Enabled 1", source_type=SourceType.RSS, url="https://e.test/1"),
            Source(
                name="Disabled",
                source_type=SourceType.HTML,
                url="https://e.test/2",
                enabled=False,
            ),
            Source(name="Enabled 2", source_type=SourceType.HTML, url="https://e.test/3"),
        ]
    )
    await session.commit()

    selected = await list_enabled_sources(session)

    assert [source.name for source in selected] == ["Enabled 1", "Enabled 2"]


@pytest.mark.asyncio
async def test_eligible_news_selection_filters_relations_orders_and_limits(
    session: AsyncSession,
) -> None:
    source = Source(
        name="Pipeline source",
        source_type=SourceType.RSS,
        url="https://pipeline.test/source",
    )
    session.add(source)
    await session.flush()

    def news(
        title: str,
        hash_digit: str,
        status: NewsItemStatus,
        published_at: datetime | None,
    ) -> NewsItem:
        return NewsItem(
            source_id=source.id,
            title=title,
            content_hash=hash_digit * 64,
            status=status,
            published_at=published_at,
        )

    first = news("First", "1", NewsItemStatus.NEW, datetime(2025, 1, 1, tzinfo=UTC))
    second = news("Second", "2", NewsItemStatus.NEW, datetime(2025, 1, 2, tzinfo=UTC))
    no_date = news("No date", "3", NewsItemStatus.NEW, None)
    filtered = news("Filtered", "4", NewsItemStatus.FILTERED, datetime(2024, 1, 1, tzinfo=UTC))
    failed = news("Failed", "5", NewsItemStatus.FAILED, datetime(2024, 1, 1, tzinfo=UTC))
    used = news("Used", "6", NewsItemStatus.NEW, datetime(2024, 1, 1, tzinfo=UTC))
    used.posts.append(Post(generated_text="Already used", status=PostStatus.GENERATED))
    session.add_all([first, second, no_date, filtered, failed, used])
    await session.commit()

    limited = await list_eligible_news_items(session, limit=2)
    all_eligible = await list_eligible_news_items(session, limit=10)

    assert [item.title for item in limited] == ["First", "Second"]
    assert [item.title for item in all_eligible] == ["First", "Second", "No date"]


@pytest.mark.asyncio
async def test_eligible_news_selection_honors_total_pipeline_limit(
    session: AsyncSession,
) -> None:
    source = Source(
        name="Limit source",
        source_type=SourceType.RSS,
        url="https://pipeline.test/limit",
    )
    session.add(source)
    await session.flush()
    session.add_all(
        [
            NewsItem(
                source_id=source.id,
                title=f"News {position}",
                content_hash=f"{position:064x}",
                status=NewsItemStatus.NEW,
                published_at=datetime(2025, 1, position, tzinfo=UTC),
            )
            for position in range(1, 9)
        ]
    )
    await session.commit()

    selected = await list_eligible_news_items(session, limit=2 * 3)

    assert [item.title for item in selected] == [f"News {position}" for position in range(1, 7)]


@pytest.mark.asyncio
async def test_eligible_news_selection_rejects_zero_limit(session: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await list_eligible_news_items(session, limit=0)
