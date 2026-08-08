import asyncio
import importlib
import sys
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import delete, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from alembic import command

ApiContext = tuple[httpx.AsyncClient, async_sessionmaker[AsyncSession]]
PROJECT_ROOT = Path(__file__).resolve().parents[1]


async def drop_alembic_version(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def management_app(database_url: str) -> Iterator[ModuleType]:
    """Запускает API-тесты на мигрированной временной базе PostgreSQL."""
    module_names = (
        "app.main",
        "app.api.sources",
        "app.api.keywords",
        "app.api.generate",
        "app.api.posts",
        "app.api.news",
        "app.api.health",
        "app.services.post_service",
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
async def api(
    management_app: ModuleType,
    database_url: str,
) -> AsyncIterator[ApiContext]:
    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def clean_tables() -> None:
        async with session_factory() as session:
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
    management_app.app.dependency_overrides[database.get_session] = override_session
    transport = httpx.ASGITransport(app=management_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, session_factory
    management_app.app.dependency_overrides.clear()
    await clean_tables()
    await engine.dispose()


async def create_source(client: httpx.AsyncClient, suffix: str = "one") -> dict[str, Any]:
    response = await client.post(
        "/api/sources",
        json={
            "name": f"Source {suffix}",
            "source_type": "rss",
            "url": f"https://example.com/{suffix}",
        },
    )
    assert response.status_code == 201
    return response.json()


async def create_keyword(
    client: httpx.AsyncClient,
    word: str = "python",
    keyword_type: str = "include",
) -> dict[str, Any]:
    response = await client.post(
        "/api/keywords",
        json={"word": word, "type": keyword_type},
    )
    assert response.status_code == 201
    return response.json()


@pytest.mark.asyncio
async def test_source_empty_list(api: ApiContext) -> None:
    client, _ = api
    response = await client.get("/api/sources")

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_source_create_list_and_detail(api: ApiContext) -> None:
    client, _ = api
    first = await create_source(client, "first")
    second = await create_source(client, "second")

    assert first["enabled"] is True
    assert first["last_parsed_at"] is None
    assert (await client.get(f"/api/sources/{first['id']}")).json() == first
    listed = (await client.get("/api/sources")).json()
    assert [item["id"] for item in listed] == [second["id"], first["id"]]


@pytest.mark.asyncio
async def test_source_duplicate_create_returns_409(api: ApiContext) -> None:
    client, _ = api
    await create_source(client)

    response = await client.post(
        "/api/sources",
        json={"name": "Duplicate", "source_type": "html", "url": "https://example.com/one"},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Source URL already exists"}


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("name", "  Updated  ", "Updated"),
        ("source_type", "telegram", "telegram"),
        ("url", "https://t.me/example", "https://t.me/example"),
        ("enabled", False, False),
    ],
)
@pytest.mark.asyncio
async def test_source_patch_each_field(
    api: ApiContext,
    field: str,
    value: object,
    expected: object,
) -> None:
    client, _ = api
    source = await create_source(client)

    response = await client.patch(f"/api/sources/{source['id']}", json={field: value})

    assert response.status_code == 200
    assert response.json()[field] == expected


@pytest.mark.asyncio
async def test_source_duplicate_url_update_returns_409(api: ApiContext) -> None:
    client, _ = api
    first = await create_source(client, "first")
    second = await create_source(client, "second")

    response = await client.patch(
        f"/api/sources/{second['id']}",
        json={"url": first["url"]},
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_source_disable_is_idempotent_and_row_remains(api: ApiContext) -> None:
    client, session_factory = api
    source = await create_source(client)
    source_id = source["id"]

    assert (await client.delete(f"/api/sources/{source_id}")).status_code == 204
    assert (await client.delete(f"/api/sources/{source_id}")).status_code == 204
    assert (await client.get(f"/api/sources/{source_id}")).json()["enabled"] is False
    async with session_factory() as session:
        assert await session.get(importlib.import_module("app.models").Source, source_id) is not None

    response = await client.patch(f"/api/sources/{source_id}", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["enabled"] is True


@pytest.mark.asyncio
async def test_source_filters_and_pagination(api: ApiContext) -> None:
    client, _ = api
    first = await create_source(client, "first")
    await create_source(client, "second")
    await client.patch(f"/api/sources/{first['id']}", json={"enabled": False})
    await client.patch(
        f"/api/sources/{first['id']}",
        json={"source_type": "html"},
    )

    disabled = (await client.get("/api/sources", params={"enabled": "false"})).json()
    html = (await client.get("/api/sources", params={"source_type": "html"})).json()
    page = (await client.get("/api/sources", params={"limit": 1, "offset": 1})).json()
    assert [item["id"] for item in disabled] == [first["id"]]
    assert [item["id"] for item in html] == [first["id"]]
    assert [item["id"] for item in page] == [first["id"]]


@pytest.mark.parametrize(
    ("method", "path", "payload", "status_code"),
    [
        ("get", "/api/sources/999999", None, 404),
        ("patch", "/api/sources/999999", {"name": "missing"}, 404),
        ("delete", "/api/sources/999999", None, 404),
        ("post", "/api/sources", {"name": "x", "source_type": "rss", "url": "ftp://x"}, 422),
        ("patch", "/api/sources/1", {}, 422),
        ("get", "/api/sources?limit=101", None, 422),
    ],
)
@pytest.mark.asyncio
async def test_source_errors(
    api: ApiContext,
    method: str,
    path: str,
    payload: dict[str, object] | None,
    status_code: int,
) -> None:
    client, _ = api
    response = await client.request(method, path, json=payload)

    assert response.status_code == status_code


@pytest.mark.asyncio
async def test_keyword_create_types_and_normalization(api: ApiContext) -> None:
    client, _ = api
    included = await create_keyword(client, "  PyThOn  ")
    excluded = await create_keyword(client, "Spam", "exclude")

    assert included["word"] == "python"
    assert included["type"] == "include"
    assert excluded["word"] == "spam"
    assert excluded["type"] == "exclude"
    assert (await client.get(f"/api/keywords/{included['id']}")).json() == included


@pytest.mark.asyncio
async def test_keyword_normalized_duplicate_returns_409(api: ApiContext) -> None:
    client, _ = api
    await create_keyword(client, "Python")

    response = await client.post("/api/keywords", json={"word": "  PYTHON  ", "type": "exclude"})

    assert response.status_code == 409
    assert response.json() == {"detail": "Keyword already exists"}


@pytest.mark.asyncio
async def test_keyword_duplicate_update_returns_409(api: ApiContext) -> None:
    client, _ = api
    first = await create_keyword(client, "python")
    second = await create_keyword(client, "asyncio")

    response = await client.patch(
        f"/api/keywords/{second['id']}",
        json={"word": first["word"].upper()},
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_services_rollback_after_unique_constraint_error(api: ApiContext) -> None:
    client, session_factory = api
    await create_source(client)
    await create_keyword(client)
    schemas = importlib.import_module("app.schemas")
    source_service = importlib.import_module("app.services.source_service")
    keyword_service = importlib.import_module("app.services.keyword_service")

    async with session_factory() as session:
        with pytest.raises(source_service.SourceAlreadyExistsError):
            await source_service.create_source(
                session,
                schemas.SourceCreate(
                    name="Duplicate",
                    source_type="rss",
                    url="https://example.com/one",
                ),
            )
        assert session.in_transaction() is False

        with pytest.raises(keyword_service.KeywordAlreadyExistsError):
            await keyword_service.create_keyword(
                session,
                schemas.KeywordCreate(word="PYTHON"),
            )
        assert session.in_transaction() is False


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("word", "  AsyncIO  ", "asyncio"),
        ("type", "exclude", "exclude"),
        ("enabled", False, False),
    ],
)
@pytest.mark.asyncio
async def test_keyword_patch_each_field(
    api: ApiContext,
    field: str,
    value: object,
    expected: object,
) -> None:
    client, _ = api
    keyword = await create_keyword(client)

    response = await client.patch(f"/api/keywords/{keyword['id']}", json={field: value})

    assert response.status_code == 200
    assert response.json()[field] == expected


@pytest.mark.asyncio
async def test_keyword_list_filters_and_pagination(api: ApiContext) -> None:
    client, _ = api
    included = await create_keyword(client, "python")
    excluded = await create_keyword(client, "spam", "exclude")
    await client.delete(f"/api/keywords/{included['id']}")

    disabled = (await client.get("/api/keywords", params={"enabled": "false"})).json()
    excluded_list = (await client.get("/api/keywords", params={"type": "exclude"})).json()
    page = (await client.get("/api/keywords", params={"limit": 1, "offset": 1})).json()
    assert [item["id"] for item in disabled] == [included["id"]]
    assert [item["id"] for item in excluded_list] == [excluded["id"]]
    assert [item["id"] for item in page] == [included["id"]]


@pytest.mark.asyncio
async def test_keyword_disable_is_idempotent_and_row_remains(api: ApiContext) -> None:
    client, session_factory = api
    keyword = await create_keyword(client)
    keyword_id = keyword["id"]

    assert (await client.delete(f"/api/keywords/{keyword_id}")).status_code == 204
    assert (await client.delete(f"/api/keywords/{keyword_id}")).status_code == 204
    async with session_factory() as session:
        model = importlib.import_module("app.models").Keyword
        stored = await session.get(model, keyword_id)
        assert stored is not None
        assert stored.enabled is False

    response = await client.patch(f"/api/keywords/{keyword_id}", json={"enabled": True})
    assert response.status_code == 200
    assert response.json()["enabled"] is True


@pytest.mark.parametrize(
    ("method", "path", "payload", "status_code"),
    [
        ("get", "/api/keywords/999999", None, 404),
        ("patch", "/api/keywords/999999", {"word": "missing"}, 404),
        ("delete", "/api/keywords/999999", None, 404),
        ("post", "/api/keywords", {"word": " "}, 422),
        ("patch", "/api/keywords/1", {}, 422),
        ("get", "/api/keywords?limit=0", None, 422),
    ],
)
@pytest.mark.asyncio
async def test_keyword_errors(
    api: ApiContext,
    method: str,
    path: str,
    payload: dict[str, object] | None,
    status_code: int,
) -> None:
    client, _ = api
    response = await client.request(method, path, json=payload)

    assert response.status_code == status_code


@pytest.mark.asyncio
async def test_openapi_contains_management_contract(api: ApiContext) -> None:
    client, _ = api
    document = (await client.get("/openapi.json")).json()

    expected_paths = {
        "/api/sources",
        "/api/sources/{source_id}",
        "/api/keywords",
        "/api/keywords/{keyword_id}",
    }
    assert expected_paths <= set(document["paths"])
    assert {"SourceCreate", "SourceUpdate", "SourceResponse"} <= set(
        document["components"]["schemas"]
    )
    assert {"KeywordCreate", "KeywordUpdate", "KeywordResponse"} <= set(
        document["components"]["schemas"]
    )
