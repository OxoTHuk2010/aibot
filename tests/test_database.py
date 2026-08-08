import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

UNIT_DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/aibot_test"


def load_database_module(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_env: str = "test",
    database_url: str = UNIT_DATABASE_URL,
) -> ModuleType:
    """Import the database module with isolated settings and without opening a connection."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", app_env)

    sys.modules.pop("app.database", None)
    sys.modules.pop("app.config", None)
    importlib.import_module("app.config")
    return importlib.import_module("app.database")


@pytest.mark.asyncio
async def test_engine_uses_asyncpg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = load_database_module(monkeypatch, tmp_path)
    try:
        assert database.engine.url.drivername == "postgresql+asyncpg"
        assert database.engine.dialect.driver == "asyncpg"
    finally:
        await database.dispose_engine()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("app_env", "expected_echo"),
    [("dev", True), ("test", False), ("prod", False)],
)
async def test_engine_echo_depends_on_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    app_env: str,
    expected_echo: bool,
) -> None:
    database = load_database_module(monkeypatch, tmp_path, app_env=app_env)
    try:
        assert database.engine.echo is expected_echo
    finally:
        await database.dispose_engine()


@pytest.mark.asyncio
async def test_get_session_yields_async_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = load_database_module(monkeypatch, tmp_path)
    dependency = database.get_session()
    try:
        session = await anext(dependency)
        assert isinstance(session, AsyncSession)
    finally:
        await dependency.aclose()
        await database.dispose_engine()


@pytest.mark.asyncio
async def test_get_session_closes_after_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = load_database_module(monkeypatch, tmp_path)
    session = AsyncMock(spec=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: session)

    dependency = database.get_session()
    yielded_session = await anext(dependency)
    await dependency.aclose()

    assert yielded_session is session
    session.rollback.assert_not_awaited()
    session.close.assert_awaited_once_with()
    await database.dispose_engine()


@pytest.mark.asyncio
async def test_get_session_rolls_back_closes_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = load_database_module(monkeypatch, tmp_path)
    session = AsyncMock(spec=AsyncSession)
    monkeypatch.setattr(database, "AsyncSessionLocal", lambda: session)
    expected_error = RuntimeError("database operation failed")

    dependency = database.get_session()
    assert await anext(dependency) is session

    with pytest.raises(RuntimeError) as raised:
        await dependency.athrow(expected_error)

    assert raised.value is expected_error
    session.rollback.assert_awaited_once_with()
    session.close.assert_awaited_once_with()
    await database.dispose_engine()


@pytest.mark.asyncio
async def test_dispose_engine_delegates_to_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database = load_database_module(monkeypatch, tmp_path)
    dispose = AsyncMock()
    monkeypatch.setattr(database, "engine", SimpleNamespace(dispose=dispose))

    await database.dispose_engine()

    dispose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_postgresql_connection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    database_url: str,
) -> None:
    database = load_database_module(
        monkeypatch,
        tmp_path,
        database_url=database_url,
    )
    try:
        async with database.engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
    finally:
        await database.dispose_engine()
