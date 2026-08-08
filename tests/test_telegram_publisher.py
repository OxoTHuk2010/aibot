from types import SimpleNamespace
from typing import ClassVar

import pytest

from app.publisher.telegram import (
    TelegramPublisher,
    TelegramPublisherConfigurationError,
    TelegramPublishError,
)


class FakeTelegramClient:
    authorized = True
    fail_send = False
    sent: ClassVar[list[tuple[str, str, object]]] = []
    disconnected = False

    def __init__(self, *_: object) -> None:
        type(self).disconnected = False

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        type(self).disconnected = True

    async def is_user_authorized(self) -> bool:
        return type(self).authorized

    async def send_message(self, target: str, text: str, *, parse_mode: object) -> object:
        if type(self).fail_send:
            raise RuntimeError("provider detail")
        type(self).sent.append((target, text, parse_mode))
        return SimpleNamespace(id=4242)


def publisher(**overrides: object) -> TelegramPublisher:
    values = {
        "api_id": 123,
        "api_hash": "test-hash",
        "session_name": "test-session",
        "target_channel": "@target",
        "client_factory": FakeTelegramClient,
    }
    values.update(overrides)
    return TelegramPublisher(**values)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def reset_fake_client() -> None:
    FakeTelegramClient.authorized = True
    FakeTelegramClient.fail_send = False
    FakeTelegramClient.sent = []
    FakeTelegramClient.disconnected = False


@pytest.mark.asyncio
async def test_publisher_sends_plain_text_and_returns_message_id() -> None:
    message_id = await publisher().publish("  Generated post  ")

    assert message_id == 4242
    assert FakeTelegramClient.sent == [("@target", "Generated post", None)]
    assert FakeTelegramClient.disconnected is True


@pytest.mark.asyncio
async def test_publisher_requires_configuration_and_authorized_session() -> None:
    with pytest.raises(TelegramPublisherConfigurationError):
        await publisher(api_id=None).publish("Post")

    FakeTelegramClient.authorized = False
    with pytest.raises(TelegramPublisherConfigurationError):
        await publisher().publish("Post")
    assert FakeTelegramClient.disconnected is True


@pytest.mark.asyncio
async def test_publisher_maps_provider_failure() -> None:
    FakeTelegramClient.fail_send = True

    with pytest.raises(TelegramPublishError, match="Telegram publication failed"):
        await publisher().publish("Post")
    assert FakeTelegramClient.disconnected is True
