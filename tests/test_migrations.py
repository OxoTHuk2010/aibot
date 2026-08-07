import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command

PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_TABLES = {
    "alembic_version",
    "keywords",
    "news",
    "post_news_items",
    "posts",
    "sources",
}


def get_alembic_config() -> Config:
    return Config(str(PROJECT_ROOT / "alembic.ini"))


def inspect_schema(connection: Any) -> dict[str, Any]:
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    schema: dict[str, Any] = {"tables": tables}

    for table in sorted(tables):
        schema[table] = {
            "columns": {column["name"]: column for column in inspector.get_columns(table)},
            "pk": set(inspector.get_pk_constraint(table).get("constrained_columns", [])),
            "foreign_keys": inspector.get_foreign_keys(table),
            "unique": {
                tuple(item["column_names"])
                for item in inspector.get_unique_constraints(table)
            },
            "checks": [item["sqltext"] for item in inspector.get_check_constraints(table)],
            "indexes": {
                (item["name"], tuple(item["column_names"]), item["unique"])
                for item in inspector.get_indexes(table)
                if not item.get("duplicates_constraint")
            },
        }

    return schema


async def load_schema(url: str) -> dict[str, Any]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(inspect_schema)
    finally:
        await engine.dispose()


async def load_table_names(url: str) -> set[str]:
    engine = create_async_engine(url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
    finally:
        await engine.dispose()


async def drop_empty_alembic_version_table(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        await engine.dispose()


def prepare_clean_database(alembic_config: Config, url: str) -> None:
    """Reset only an Alembic-managed schema and prove that no tables remain."""
    tables = asyncio.run(load_table_names(url))
    if "alembic_version" in tables:
        command.downgrade(alembic_config, "base")

    remaining_tables = asyncio.run(load_table_names(url))
    unexpected_tables = remaining_tables - {"alembic_version"}
    if unexpected_tables:
        pytest.fail("TEST_DATABASE_URL does not reference a clean Alembic test database")

    asyncio.run(drop_empty_alembic_version_table(url))
    assert asyncio.run(load_table_names(url)) == set()


def assert_check_values(checks: list[str], expected_values: set[str]) -> None:
    sql = " ".join(checks)
    assert all(value in sql for value in expected_values)


def assert_initial_schema(schema: dict[str, Any]) -> None:
    assert schema["tables"] == EXPECTED_TABLES
    assert set(schema["sources"]["columns"]) == {
        "id",
        "name",
        "source_type",
        "url",
        "enabled",
        "last_parsed_at",
        "created_at",
        "updated_at",
    }
    assert set(schema["news"]["columns"]) == {
        "id",
        "source_id",
        "external_id",
        "title",
        "url",
        "summary",
        "raw_text",
        "published_at",
        "content_hash",
        "status",
        "error_message",
        "created_at",
        "updated_at",
    }
    assert set(schema["posts"]["columns"]) == {
        "id",
        "generated_text",
        "status",
        "error_message",
        "telegram_message_id",
        "published_at",
        "created_at",
        "updated_at",
    }
    assert set(schema["keywords"]["columns"]) == {
        "id",
        "word",
        "type",
        "enabled",
        "created_at",
        "updated_at",
    }
    assert set(schema["post_news_items"]["columns"]) == {"post_id", "news_item_id"}

    assert schema["post_news_items"]["pk"] == {"post_id", "news_item_id"}
    assert ("url",) in schema["sources"]["unique"]
    assert ("content_hash",) in schema["news"]["unique"]
    assert ("telegram_message_id",) in schema["posts"]["unique"]
    assert ("word",) in schema["keywords"]["unique"]

    news_fk = schema["news"]["foreign_keys"]
    assert len(news_fk) == 1
    assert news_fk[0]["constrained_columns"] == ["source_id"]
    assert news_fk[0]["referred_table"] == "sources"
    assert news_fk[0]["options"].get("ondelete") == "CASCADE"

    association_fks = schema["post_news_items"]["foreign_keys"]
    assert {foreign_key["referred_table"] for foreign_key in association_fks} == {
        "news",
        "posts",
    }
    assert {foreign_key["options"].get("ondelete") for foreign_key in association_fks} == {
        "CASCADE"
    }

    assert_check_values(schema["sources"]["checks"], {"rss", "html", "telegram"})
    assert_check_values(schema["news"]["checks"], {"new", "filtered", "failed"})
    assert_check_values(schema["posts"]["checks"], {"generated", "published", "failed"})
    assert_check_values(schema["keywords"]["checks"], {"include", "exclude"})

    assert schema["sources"]["indexes"] == {("ix_sources_enabled", ("enabled",), False)}
    assert schema["news"]["indexes"] == {("ix_news_source_id", ("source_id",), False)}

    for table in ("sources", "news", "posts", "keywords"):
        for column_name in ("created_at", "updated_at"):
            column = schema[table]["columns"][column_name]
            assert column["nullable"] is False
            assert column["default"] is not None
            assert column["type"].timezone is True

    assert schema["sources"]["columns"]["last_parsed_at"]["nullable"] is True
    assert schema["sources"]["columns"]["last_parsed_at"]["default"] is None
    assert schema["news"]["columns"]["published_at"]["nullable"] is True
    assert schema["news"]["columns"]["published_at"]["default"] is None
    assert schema["posts"]["columns"]["published_at"]["nullable"] is True
    assert schema["posts"]["columns"]["published_at"]["default"] is None


def test_initial_migration_on_postgresql(
    monkeypatch: pytest.MonkeyPatch,
    test_database_url: str,
) -> None:
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("APP_ENV", "test")
    for module_name in ("app.models", "app.database", "app.config"):
        sys.modules.pop(module_name, None)

    alembic_config = get_alembic_config()
    prepare_clean_database(alembic_config, test_database_url)

    command.upgrade(alembic_config, "head")
    assert_initial_schema(asyncio.run(load_schema(test_database_url)))

    command.downgrade(alembic_config, "base")
    assert asyncio.run(load_table_names(test_database_url)) == {"alembic_version"}

    command.upgrade(alembic_config, "head")
    assert_initial_schema(asyncio.run(load_schema(test_database_url)))

    command.check(alembic_config)

    database = importlib.import_module("app.database")
    asyncio.run(database.dispose_engine())
