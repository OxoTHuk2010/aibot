import asyncio
import importlib
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest
from pydantic import ValidationError

UNIT_DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/aibot_test"


@pytest.fixture(scope="module")
def schemas(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ModuleType]:
    """Загружает схемы без чтения environment и открытия соединения с базой данных."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.chdir(tmp_path_factory.mktemp("schema-settings"))
    monkeypatch.setenv("DATABASE_URL", UNIT_DATABASE_URL)
    monkeypatch.setenv("APP_ENV", "test")

    for module_name in ("app.schemas", "app.models", "app.database", "app.config"):
        sys.modules.pop(module_name, None)

    module = importlib.import_module("app.schemas")
    yield module

    database = importlib.import_module("app.database")
    asyncio.run(database.dispose_engine())
    monkeypatch.undo()


def test_source_create_normalizes_name_and_accepts_http_url(schemas: ModuleType) -> None:
    data = schemas.SourceCreate(
        name="  Example feed  ",
        source_type="rss",
        url="https://example.com/rss",
    )

    assert data.name == "Example feed"
    assert str(data.url) == "https://example.com/rss"
    assert data.enabled is True


@pytest.mark.parametrize(
    "payload",
    [
        {"name": " ", "source_type": "rss", "url": "https://example.com"},
        {"name": "feed", "source_type": "rss", "url": "ftp://example.com/feed"},
        {"name": "feed", "source_type": "other", "url": "https://example.com"},
        {
            "name": "feed",
            "source_type": "rss",
            "url": "https://example.com",
            "id": 1,
        },
    ],
)
def test_source_create_rejects_invalid_input(
    schemas: ModuleType,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        schemas.SourceCreate.model_validate(payload)


@pytest.mark.parametrize("payload", [{}, {"name": None}, {"enabled": None}, {"url": None}])
def test_source_update_rejects_empty_or_null_patch(
    schemas: ModuleType,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        schemas.SourceUpdate.model_validate(payload)


def test_keyword_create_normalizes_word_and_defaults(schemas: ModuleType) -> None:
    data = schemas.KeywordCreate(word="  NeWs  ")

    assert data.word == "news"
    assert data.type.value == "include"
    assert data.enabled is True


@pytest.mark.parametrize(
    "payload",
    [
        {"word": " "},
        {"word": "news", "type": "other"},
        {"word": "news", "created_at": "2026-01-01T00:00:00Z"},
    ],
)
def test_keyword_create_rejects_invalid_input(
    schemas: ModuleType,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        schemas.KeywordCreate.model_validate(payload)


@pytest.mark.parametrize("payload", [{}, {"word": None}, {"type": None}, {"enabled": None}])
def test_keyword_update_rejects_empty_or_null_patch(
    schemas: ModuleType,
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        schemas.KeywordUpdate.model_validate(payload)


def test_keyword_update_normalizes_word(schemas: ModuleType) -> None:
    data = schemas.KeywordUpdate(word="  Python  ")

    assert data.word == "python"
    assert data.model_fields_set == {"word"}
