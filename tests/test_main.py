import asyncio
import importlib
import sys
from collections.abc import Iterator
from types import ModuleType
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

TEST_DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/aibot_test"


@pytest.fixture(scope="module")
def main_module(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ModuleType]:
    """Import the ASGI app without reading the developer's real environment or .env."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.chdir(tmp_path_factory.mktemp("main-settings"))
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setenv("APP_ENV", "test")

    for module_name in ("app.main", "app.database", "app.config"):
        sys.modules.pop(module_name, None)

    module = importlib.import_module("app.main")
    yield module

    database = importlib.import_module("app.database")
    asyncio.run(database.dispose_engine())
    monkeypatch.undo()


def test_app_is_importable(main_module: ModuleType) -> None:
    assert isinstance(main_module.app, FastAPI)


async def get(main_module: ModuleType, path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=main_module.app)
    async with (
        main_module.app.router.lifespan_context(main_module.app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        return await client.get(path)


@pytest.mark.asyncio
async def test_health_is_process_liveness(main_module: ModuleType) -> None:
    response = await get(main_module, "/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_docs_are_available(main_module: ModuleType) -> None:
    response = await get(main_module, "/docs")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_openapi_is_available_and_contains_health(main_module: ModuleType) -> None:
    response = await get(main_module, "/openapi.json")

    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]


@pytest.mark.asyncio
async def test_lifespan_disposes_engine(
    main_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispose_engine = AsyncMock()
    monkeypatch.setattr(main_module, "dispose_engine", dispose_engine)

    async with main_module.app.router.lifespan_context(main_module.app):
        pass

    dispose_engine.assert_awaited_once_with()
