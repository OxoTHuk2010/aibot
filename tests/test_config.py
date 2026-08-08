import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

ASYNC_DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/aibot_test"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_ENV_NAMES = (
    "DATABASE_URL",
    "RABBITMQ_URL",
    "REDIS_URL",
    "TELEGRAM_API_ID",
    "TELEGRAM_API_HASH",
    "TELEGRAM_SESSION_NAME",
    "TELEGRAM_TARGET_CHANNEL",
    "TELEGRAM_PUBLISHER",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_TARGET_CHAT_ID",
    "AI_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_MAX_TOKENS",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "OLLAMA_TIMEOUT",
    "PARSE_INTERVAL",
    "MAX_NEWS_PER_SOURCE",
    "AUTO_PUBLISH",
    "PIPELINE_MAX_POSTS_PER_RUN",
    "PIPELINE_NEWS_PER_POST",
    "APP_ENV",
    "LOG_LEVEL",
    "APP_NAME",
)


@pytest.fixture
def settings_class(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> type[Any]:
    """Import config without reading the developer's environment or .env file."""
    monkeypatch.chdir(tmp_path)
    for name in CONFIG_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", ASYNC_DATABASE_URL)

    sys.modules.pop("app.config", None)
    module = importlib.import_module("app.config")
    return module.Settings


def make_settings(settings_class: type[Any], **overrides: object) -> Any:
    """Build settings without reading the developer's real .env file."""
    values: dict[str, object] = {"database_url": ASYNC_DATABASE_URL, **overrides}
    return settings_class(_env_file=None, **values)


def test_minimal_configuration_loads(settings_class: type[Any]) -> None:
    settings = make_settings(settings_class)

    assert settings.database_url == ASYNC_DATABASE_URL
    assert settings.redis_url is None
    assert settings.rabbitmq_url is None
    assert settings.openai_api_key is None
    assert settings.telegram_api_id is None
    assert settings.telegram_api_hash is None
    assert settings.telegram_target_channel is None
    assert settings.telegram_bot_token is None
    assert settings.telegram_target_chat_id is None
    assert settings.ai_provider == "openai"
    assert settings.telegram_publisher == "telethon"
    assert settings.auto_publish is False
    assert settings.pipeline_max_posts_per_run == 2
    assert settings.pipeline_news_per_post == 5


def test_database_url_is_required(
    settings_class: type[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValidationError, match="database_url"):
        settings_class(_env_file=None)


def test_sync_postgresql_url_is_rejected(settings_class: type[Any]) -> None:
    with pytest.raises(ValidationError, match=r"postgresql\+asyncpg"):
        make_settings(
            settings_class,
            database_url="postgresql://user:password@localhost:5432/aibot_test",
        )


def test_async_postgresql_url_is_accepted(settings_class: type[Any]) -> None:
    assert make_settings(settings_class).database_url.startswith("postgresql+asyncpg://")


def test_compose_variables_in_env_file_are_ignored(
    settings_class: type[Any],
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            (
                f"DATABASE_URL={ASYNC_DATABASE_URL}",
                "POSTGRES_DB=aibot_test",
                "POSTGRES_USER=aibot",
                "POSTGRES_PASSWORD=not-a-real-secret",
                "RABBITMQ_USER=aibot",
                "RABBITMQ_PASSWORD=not-a-real-secret",
            )
        ),
        encoding="utf-8",
    )

    settings = settings_class(_env_file=env_file)

    assert settings.database_url == ASYNC_DATABASE_URL
    assert settings.rabbitmq_url is None


def test_example_environment_file_loads(
    settings_class: type[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    settings = settings_class(_env_file=PROJECT_ROOT / ".env.example")

    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_test_environment_is_accepted(settings_class: type[Any]) -> None:
    assert make_settings(settings_class, app_env="test").app_env == "test"


def test_unknown_environment_is_rejected(settings_class: type[Any]) -> None:
    with pytest.raises(ValidationError, match="app_env"):
        make_settings(settings_class, app_env="staging")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ai_provider", "unknown"),
        ("telegram_publisher", "unknown"),
    ],
)
def test_unknown_backend_is_rejected(
    settings_class: type[Any],
    field: str,
    value: str,
) -> None:
    with pytest.raises(ValidationError, match=field):
        make_settings(settings_class, **{field: value})


@pytest.mark.parametrize("url", ["localhost:11434", "http://", "file:///tmp/ollama"])
def test_invalid_ollama_base_url_is_rejected(
    settings_class: type[Any],
    url: str,
) -> None:
    with pytest.raises(ValidationError, match="ollama_base_url"):
        make_settings(settings_class, ollama_base_url=url)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("openai_max_tokens", 49),
        ("openai_max_tokens", 4001),
        ("parse_interval", 0),
        ("max_news_per_source", 0),
        ("max_news_per_source", 101),
        ("ollama_timeout", 0),
        ("ollama_timeout", 601),
        ("pipeline_max_posts_per_run", 0),
        ("pipeline_max_posts_per_run", 11),
        ("pipeline_news_per_post", 0),
        ("pipeline_news_per_post", 11),
    ],
)
def test_numeric_limits_are_enforced(
    settings_class: type[Any],
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError, match=field):
        make_settings(settings_class, **{field: value})


def test_numeric_boundary_values_are_accepted(settings_class: type[Any]) -> None:
    settings = make_settings(
        settings_class,
        openai_max_tokens=50,
        parse_interval=1,
        max_news_per_source=100,
    )

    assert settings.openai_max_tokens == 50
    assert settings.parse_interval == 1
    assert settings.max_news_per_source == 100
