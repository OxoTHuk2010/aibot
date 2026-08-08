from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from app.ai.client import AIClient, AIConfigurationError
from app.ai.ollama import OllamaClient
from app.api import generate as generate_api
from app.api import posts as posts_api
from app.publisher.bot import TelegramBotPublisher
from app.publisher.telegram import (
    TelegramPublisher,
    TelegramPublisherConfigurationError,
)


def ai_settings(provider: str) -> SimpleNamespace:
    return SimpleNamespace(
        ai_provider=provider,
        openai_api_key=SecretStr("test-only-openai-key"),
        openai_model="openai-test-model",
        openai_max_tokens=100,
        ollama_base_url="http://ollama.test:11434",
        ollama_model="gemma4:e4b",
        ollama_timeout=10.0,
    )


def telegram_settings(publisher: str) -> SimpleNamespace:
    return SimpleNamespace(
        telegram_publisher=publisher,
        telegram_api_id=123,
        telegram_api_hash=SecretStr("test-only-api-hash"),
        telegram_session_name="test-session",
        telegram_target_channel="@test",
        telegram_bot_token=SecretStr("test-only-bot-token"),
        telegram_target_chat_id="-1001234567890",
    )


@pytest.mark.parametrize(
    ("provider", "expected_type"),
    [("openai", AIClient), ("ollama", OllamaClient)],
)
def test_ai_provider_selection(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    expected_type: type[object],
) -> None:
    monkeypatch.setattr(generate_api, "settings", ai_settings(provider))

    assert isinstance(generate_api.get_generator().client, expected_type)


def test_unknown_ai_provider_is_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(generate_api, "settings", ai_settings("unknown"))

    with pytest.raises(AIConfigurationError):
        generate_api.get_generator()


@pytest.mark.parametrize(
    ("publisher", "expected_type"),
    [("telethon", TelegramPublisher), ("bot", TelegramBotPublisher)],
)
def test_telegram_publisher_selection(
    monkeypatch: pytest.MonkeyPatch,
    publisher: str,
    expected_type: type[object],
) -> None:
    monkeypatch.setattr(posts_api, "settings", telegram_settings(publisher))

    assert isinstance(posts_api.get_publisher(), expected_type)


def test_unknown_telegram_publisher_is_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(posts_api, "settings", telegram_settings("unknown"))

    with pytest.raises(TelegramPublisherConfigurationError):
        posts_api.get_publisher()
