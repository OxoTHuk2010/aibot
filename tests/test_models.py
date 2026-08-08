import asyncio
import importlib
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest
from sqlalchemy import BigInteger, CheckConstraint, String, Text
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import configure_mappers

UNIT_DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/aibot_test"


@pytest.fixture(scope="module")
def models(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ModuleType]:
    """Import model metadata without reading the developer's real environment or .env."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.chdir(tmp_path_factory.mktemp("model-settings"))
    monkeypatch.setenv("DATABASE_URL", UNIT_DATABASE_URL)
    monkeypatch.setenv("APP_ENV", "test")

    sys.modules.pop("app.models", None)
    sys.modules.pop("app.database", None)
    sys.modules.pop("app.config", None)
    importlib.import_module("app.config")
    database = importlib.import_module("app.database")
    models_module = importlib.import_module("app.models")

    yield models_module

    asyncio.run(database.dispose_engine())
    monkeypatch.undo()


def test_mappers_configure(models: ModuleType) -> None:
    configure_mappers()


def test_news_item_physical_table_contract(models: ModuleType) -> None:
    assert models.NewsItem.__tablename__ == "news_items"
    assert "news_items" in models.Base.metadata.tables
    assert "news" not in models.Base.metadata.tables

    news_item_foreign_key = next(
        foreign_key
        for foreign_key in models.post_news_items.foreign_keys
        if foreign_key.parent.name == "news_item_id"
    )
    assert news_item_foreign_key.target_fullname == "news_items.id"


def test_enum_values(models: ModuleType) -> None:
    assert {item.value for item in models.SourceType} == {"rss", "html", "telegram"}
    assert {item.value for item in models.NewsItemStatus} == {"new", "filtered", "failed"}
    assert {item.value for item in models.PostStatus} == {"generated", "published", "failed"}
    assert {item.value for item in models.KeywordType} == {"include", "exclude"}
    assert not hasattr(models.NewsItemStatus, "GENERATED")
    assert not hasattr(models.NewsItemStatus, "PUBLISHED")


@pytest.mark.parametrize(
    ("model_name", "column_name", "expected_values"),
    [
        ("Source", "source_type", ["rss", "html", "telegram"]),
        ("NewsItem", "status", ["new", "filtered", "failed"]),
        ("Post", "status", ["generated", "published", "failed"]),
        ("Keyword", "type", ["include", "exclude"]),
    ],
)
def test_enum_columns_are_check_backed(
    models: ModuleType,
    model_name: str,
    column_name: str,
    expected_values: list[str],
) -> None:
    table = getattr(models, model_name).__table__
    column = table.c[column_name]

    assert isinstance(column.type, SqlEnum)
    assert column.type.native_enum is False
    assert column.type.create_constraint is True
    assert column.type.enums == expected_values
    assert any(isinstance(constraint, CheckConstraint) for constraint in table.constraints)


def test_nullable_semantics(models: ModuleType) -> None:
    assert models.Source.__table__.c.last_parsed_at.nullable is True
    assert models.NewsItem.__table__.c.external_id.nullable is True
    assert models.NewsItem.__table__.c.published_at.nullable is True
    assert models.Post.__table__.c.published_at.nullable is True
    assert models.Post.__table__.c.telegram_message_id.nullable is True
    assert models.Post.__table__.c.generated_text.nullable is False


def test_telegram_message_id_is_unique_big_integer(models: ModuleType) -> None:
    column = models.Post.__table__.c.telegram_message_id

    assert column.unique is True
    assert isinstance(column.type, BigInteger)


def test_content_hash_is_sha256_sized_and_unique(models: ModuleType) -> None:
    table = models.NewsItem.__table__
    column = table.c.content_hash

    assert isinstance(column.type, String)
    assert column.type.length == 64
    assert column.unique is True
    assert all(column.name not in index.columns for index in table.indexes)


def test_text_columns(models: ModuleType) -> None:
    assert isinstance(models.NewsItem.__table__.c.summary.type, Text)
    assert isinstance(models.NewsItem.__table__.c.raw_text.type, Text)
    assert isinstance(models.NewsItem.__table__.c.error_message.type, Text)
    assert isinstance(models.Post.__table__.c.error_message.type, Text)


def test_all_datetime_columns_are_timezone_aware(models: ModuleType) -> None:
    datetime_columns = (
        models.Source.__table__.c.last_parsed_at,
        models.Source.__table__.c.created_at,
        models.Source.__table__.c.updated_at,
        models.NewsItem.__table__.c.published_at,
        models.NewsItem.__table__.c.created_at,
        models.NewsItem.__table__.c.updated_at,
        models.Post.__table__.c.published_at,
        models.Post.__table__.c.created_at,
        models.Post.__table__.c.updated_at,
        models.Keyword.__table__.c.created_at,
        models.Keyword.__table__.c.updated_at,
    )

    assert all(column.type.timezone is True for column in datetime_columns)


def test_timestamp_defaults_and_updates(models: ModuleType) -> None:
    created_at_columns = (
        models.Source.__table__.c.created_at,
        models.NewsItem.__table__.c.created_at,
        models.Post.__table__.c.created_at,
        models.Keyword.__table__.c.created_at,
    )
    updated_at_columns = (
        models.Source.__table__.c.updated_at,
        models.NewsItem.__table__.c.updated_at,
        models.Post.__table__.c.updated_at,
        models.Keyword.__table__.c.updated_at,
    )
    event_time_columns = (
        models.Source.__table__.c.last_parsed_at,
        models.NewsItem.__table__.c.published_at,
        models.Post.__table__.c.published_at,
    )

    assert all(column.nullable is False for column in created_at_columns)
    assert all(column.server_default is not None for column in created_at_columns)
    assert all(column.nullable is False for column in updated_at_columns)
    assert all(column.server_default is not None for column in updated_at_columns)
    assert all(column.onupdate is not None for column in updated_at_columns)
    assert all(column.default is None for column in event_time_columns)
    assert all(column.server_default is None for column in event_time_columns)


def test_post_has_no_direct_news_foreign_key(models: ModuleType) -> None:
    assert "news_id" not in models.Post.__table__.c
    assert not hasattr(models.Post, "news_id")


def test_post_and_news_item_have_collection_relationships(models: ModuleType) -> None:
    post_relationship = models.Post.__mapper__.relationships["news_items"]
    news_relationship = models.NewsItem.__mapper__.relationships["posts"]

    assert post_relationship.uselist is True
    assert news_relationship.uselist is True
    assert post_relationship.secondary is models.post_news_items
    assert news_relationship.secondary is models.post_news_items


def test_association_table_has_unique_pair_and_cascade_foreign_keys(models: ModuleType) -> None:
    table = models.post_news_items

    assert {column.name for column in table.primary_key.columns} == {"post_id", "news_item_id"}
    assert {foreign_key.ondelete for foreign_key in table.foreign_keys} == {"CASCADE"}


def test_source_owns_news_items(models: ModuleType) -> None:
    relationship = models.Source.__mapper__.relationships["news_items"]
    source_id = models.NewsItem.__table__.c.source_id

    assert "delete" in relationship.cascade
    assert "delete-orphan" in relationship.cascade
    assert {foreign_key.ondelete for foreign_key in source_id.foreign_keys} == {"CASCADE"}


def test_many_to_many_relationships_do_not_delete_domain_entities(models: ModuleType) -> None:
    post_relationship = models.Post.__mapper__.relationships["news_items"]
    news_relationship = models.NewsItem.__mapper__.relationships["posts"]

    assert "delete" not in post_relationship.cascade
    assert "delete-orphan" not in post_relationship.cascade
    assert "delete" not in news_relationship.cascade
    assert "delete-orphan" not in news_relationship.cascade
