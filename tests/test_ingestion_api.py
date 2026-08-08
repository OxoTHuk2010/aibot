import asyncio
import importlib
import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ApiContext = tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]]


async def drop_alembic_version(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def ingestion_app(database_url: str) -> Iterator[ModuleType]:
    module_names = (
        "app.main",
        "app.api.health",
        "app.api.keywords",
        "app.api.sources",
        "app.api.news",
        "app.api.generate",
        "app.api.posts",
        "app.services.post_service",
        "app.services.news_service",
        "app.services.filter_service",
        "app.services.source_service",
        "app.services.keyword_service",
        "app.schemas",
        "app.models",
        "app.database",
        "app.config",
    )
    for module_name in module_names:
        sys.modules.pop(module_name, None)

    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")
    for module_name in module_names:
        sys.modules.pop(module_name, None)

    module = importlib.import_module("app.main")
    yield module

    database = importlib.import_module("app.database")
    asyncio.run(database.dispose_engine())
    command.downgrade(alembic_config, "base")
    asyncio.run(drop_alembic_version(database_url))


@pytest.fixture
async def api(ingestion_app: ModuleType, database_url: str) -> AsyncIterator[ApiContext]:
    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def clean_tables() -> None:
        async with session_factory() as session:
            await session.execute(delete(models.NewsItem))
            await session.execute(delete(models.Keyword))
            await session.execute(delete(models.Source))
            await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        session = session_factory()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    await clean_tables()
    ingestion_app.app.dependency_overrides[database.get_session] = override_session
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ingestion_app.app),
        base_url="http://test",
    ) as client:
        yield client, session_factory
    ingestion_app.app.dependency_overrides.clear()
    await clean_tables()
    await engine.dispose()


class FakeParser:
    def __init__(self, items: list[object]) -> None:
        self.items = items

    async def parse(self, _: object) -> list[object]:
        return self.items


class FailingParser:
    async def parse(self, _: object) -> list[object]:
        parser_base = importlib.import_module("app.parser.base")
        raise parser_base.ParserError("fixture failure")


def parsed_item(
    title: str,
    *,
    url: str | None = None,
    summary: str | None = None,
    raw_text: str | None = None,
    published_at: datetime | None = None,
    external_id: str | None = None,
) -> object:
    dto = importlib.import_module("app.parser.base").ParsedNewsItem
    return dto(
        title=title,
        url=url,
        summary=summary,
        raw_text=raw_text,
        published_at=published_at,
        external_id=external_id,
    )


def use_parser(monkeypatch: pytest.MonkeyPatch, parser: object) -> None:
    service = importlib.import_module("app.services.news_service")
    monkeypatch.setattr(service, "create_parser", lambda *_: parser)


async def create_source(
    client: httpx.AsyncClient,
    *,
    suffix: str = "one",
    enabled: bool = True,
    source_type: str = "rss",
) -> dict[str, Any]:
    response = await client.post(
        "/api/sources",
        json={
            "name": f"Source {suffix}",
            "source_type": source_type,
            "url": f"https://example.com/{suffix}",
            "enabled": enabled,
        },
    )
    assert response.status_code == 201
    return response.json()


async def create_keyword(
    client: httpx.AsyncClient,
    word: str,
    keyword_type: str,
) -> dict[str, Any]:
    response = await client.post(
        "/api/keywords",
        json={"word": word, "type": keyword_type},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_parse_pipeline_persists_hashes_filters_and_timestamp(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = api
    source = await create_source(client)
    await create_keyword(client, "python", "include")
    await create_keyword(client, "spam", "exclude")
    use_parser(
        monkeypatch,
        FakeParser(
            [
                parsed_item(
                    "Python release",
                    url="HTTPS://Example.COM/story#fragment",
                    published_at=datetime(2025, 8, 8, tzinfo=UTC),
                    external_id="one",
                ),
                parsed_item("Python spam", raw_text="excluded text", external_id="two"),
                parsed_item("Unmatched story", raw_text="other", external_id="three"),
            ]
        ),
    )

    response = await client.post(f"/api/sources/{source['id']}/parse")

    assert response.status_code == 200
    assert response.json() == {
        "source_id": source["id"],
        "found": 3,
        "created": 3,
        "duplicates": 0,
        "filtered": 2,
        "errors": 0,
    }
    news = (await client.get("/api/news")).json()
    assert {item["status"] for item in news} == {"new", "filtered"}
    assert all(len(item["content_hash"]) == 64 for item in news)
    assert next(item for item in news if item["external_id"] == "one")["url"] == (
        "https://example.com/story"
    )
    source_detail = (await client.get(f"/api/sources/{source['id']}")).json()
    assert source_detail["last_parsed_at"] is not None

    models = importlib.import_module("app.models")
    async with session_factory() as session:
        stored = list((await session.scalars(select(models.NewsItem))).all())
        assert len(stored) == 3


@pytest.mark.asyncio
async def test_repeated_parse_suppresses_duplicates(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api
    source = await create_source(client)
    use_parser(
        monkeypatch,
        FakeParser([parsed_item("Same story", url="https://example.com/story")]),
    )

    first = await client.post(f"/api/sources/{source['id']}/parse")
    second = await client.post(f"/api/sources/{source['id']}/parse")

    assert first.json()["created"] == 1
    assert second.json()["created"] == 0
    assert second.json()["duplicates"] == 1
    assert len((await client.get("/api/news")).json()) == 1


@pytest.mark.asyncio
async def test_invalid_item_is_counted_without_failing_run(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api
    source = await create_source(client)
    use_parser(monkeypatch, FakeParser([parsed_item(" "), parsed_item("Valid story")]))

    response = await client.post(f"/api/sources/{source['id']}/parse")

    assert response.status_code == 200
    assert response.json()["found"] == 2
    assert response.json()["created"] == 1
    assert response.json()["errors"] == 1


@pytest.mark.asyncio
async def test_parse_missing_and_disabled_source_errors(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api
    use_parser(monkeypatch, FakeParser([]))
    disabled = await create_source(client, enabled=False)

    assert (await client.post("/api/sources/999999/parse")).status_code == 404
    response = await client.post(f"/api/sources/{disabled['id']}/parse")
    assert response.status_code == 409
    assert response.json() == {"detail": "Source is disabled"}


@pytest.mark.asyncio
async def test_parser_failure_is_safe_and_does_not_update_source(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api
    source = await create_source(client)
    use_parser(monkeypatch, FailingParser())

    response = await client.post(f"/api/sources/{source['id']}/parse")

    assert response.status_code == 502
    assert response.json() == {"detail": "Source fetch or parsing failed"}
    detail = (await client.get(f"/api/sources/{source['id']}")).json()
    assert detail["last_parsed_at"] is None


@pytest.mark.asyncio
async def test_parser_configuration_error_is_mapped_without_secrets(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api
    source = await create_source(client, source_type="telegram")
    parser_base = importlib.import_module("app.parser.base")
    service = importlib.import_module("app.services.news_service")

    def not_configured(*_: object) -> object:
        raise parser_base.ParserConfigurationError("secret internal detail")

    monkeypatch.setattr(service, "create_parser", not_configured)
    response = await client.post(f"/api/sources/{source['id']}/parse")

    assert response.status_code == 409
    assert response.json() == {"detail": "Source parser is not configured"}
    assert "secret" not in response.text


@pytest.mark.asyncio
async def test_news_read_api_filters_paginates_and_returns_detail(
    api: ApiContext,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = api
    assert (await client.get("/api/news")).json() == []
    first_source = await create_source(client, suffix="first")
    second_source = await create_source(client, suffix="second")

    use_parser(
        monkeypatch,
        FakeParser(
            [
                parsed_item(
                    "First",
                    url="https://example.com/first-item",
                    published_at=datetime(2025, 8, 8, tzinfo=UTC),
                ),
                parsed_item("Undated", raw_text="body"),
            ]
        ),
    )
    await client.post(f"/api/sources/{first_source['id']}/parse")
    await create_keyword(client, "required", "include")
    use_parser(monkeypatch, FakeParser([parsed_item("Filtered", raw_text="other")]))
    await client.post(f"/api/sources/{second_source['id']}/parse")

    by_source = (
        await client.get("/api/news", params={"source_id": first_source["id"]})
    ).json()
    filtered = (await client.get("/api/news", params={"status": "filtered"})).json()
    first_page = (await client.get("/api/news", params={"limit": 1, "offset": 0})).json()
    second_page = (await client.get("/api/news", params={"limit": 1, "offset": 1})).json()

    assert len(by_source) == 2
    assert len(filtered) == 1
    assert filtered[0]["source_id"] == second_source["id"]
    assert len(first_page) == len(second_page) == 1
    assert first_page[0]["id"] != second_page[0]["id"]
    detail = await client.get(f"/api/news/{first_page[0]['id']}")
    assert detail.status_code == 200
    assert detail.json()["id"] == first_page[0]["id"]
    assert (await client.get("/api/news/999999")).status_code == 404
    assert (await client.get("/api/news", params={"limit": 101})).status_code == 422
