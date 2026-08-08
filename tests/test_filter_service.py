import asyncio
import importlib
import sys
from collections.abc import Iterator
from types import ModuleType, SimpleNamespace

import pytest

UNIT_DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/aibot_test"


@pytest.fixture(scope="module")
def filter_modules(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[ModuleType, ModuleType]]:
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.chdir(tmp_path_factory.mktemp("filter-settings"))
    monkeypatch.setenv("DATABASE_URL", UNIT_DATABASE_URL)
    monkeypatch.setenv("APP_ENV", "test")
    for module_name in (
        "app.services.filter_service",
        "app.models",
        "app.database",
        "app.config",
    ):
        sys.modules.pop(module_name, None)

    service = importlib.import_module("app.services.filter_service")
    models = importlib.import_module("app.models")
    yield service, models

    database = importlib.import_module("app.database")
    asyncio.run(database.dispose_engine())
    monkeypatch.undo()


def item(service: ModuleType, text: str = "Python release") -> object:
    return service.ParsedNewsItem(title=text, summary=None, raw_text=None)


def keyword(models: ModuleType, word: str, keyword_type: str, *, enabled: bool = True) -> object:
    return SimpleNamespace(
        word=word,
        type=models.KeywordType(keyword_type),
        enabled=enabled,
    )


def test_no_keywords_is_new(filter_modules: tuple[ModuleType, ModuleType]) -> None:
    service, models = filter_modules
    assert service.determine_news_status(item(service), []) == models.NewsItemStatus.NEW


def test_include_match_is_new(filter_modules: tuple[ModuleType, ModuleType]) -> None:
    service, models = filter_modules
    keywords = [keyword(models, "python", "include")]
    assert service.determine_news_status(item(service), keywords) == models.NewsItemStatus.NEW


def test_include_no_match_is_filtered(filter_modules: tuple[ModuleType, ModuleType]) -> None:
    service, models = filter_modules
    keywords = [keyword(models, "rust", "include")]
    assert service.determine_news_status(item(service), keywords) == models.NewsItemStatus.FILTERED


def test_exclude_match_wins_over_include(filter_modules: tuple[ModuleType, ModuleType]) -> None:
    service, models = filter_modules
    keywords = [
        keyword(models, "python", "include"),
        keyword(models, "release", "exclude"),
    ]
    assert service.determine_news_status(item(service), keywords) == models.NewsItemStatus.FILTERED


def test_disabled_keyword_is_ignored(filter_modules: tuple[ModuleType, ModuleType]) -> None:
    service, models = filter_modules
    keywords = [keyword(models, "release", "exclude", enabled=False)]
    assert service.determine_news_status(item(service), keywords) == models.NewsItemStatus.NEW


def test_matching_is_case_insensitive(filter_modules: tuple[ModuleType, ModuleType]) -> None:
    service, models = filter_modules
    keywords = [keyword(models, "python", "include")]
    assert service.determine_news_status(item(service, "PYTHON NEWS"), keywords) == (
        models.NewsItemStatus.NEW
    )
