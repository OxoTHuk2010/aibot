import json

import httpx
import pytest

from app.publisher.bot import TelegramBotPublisher
from app.publisher.telegram import (
    TelegramPublisherConfigurationError,
    TelegramPublishError,
)


def make_publisher(
    transport: httpx.AsyncBaseTransport,
    **overrides: object,
) -> tuple[TelegramBotPublisher, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=transport)
    values = {
        "token": "test-only-token",
        "target_chat_id": "-1001234567890",
        "client": http_client,
    }
    values.update(overrides)
    return TelegramBotPublisher(**values), http_client  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_bot_api_request_and_message_id() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sendMessage")
        assert json.loads(request.content) == {
            "chat_id": "-1001234567890",
            "text": "Generated post",
        }
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 808}})

    publisher, http_client = make_publisher(httpx.MockTransport(handler))
    async with http_client:
        assert await publisher.publish("  Generated post  ") == 808


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"token": None},
        {"target_chat_id": None},
        {"target_chat_id": ""},
    ],
)
async def test_bot_api_requires_token_and_chat_id(overrides: dict[str, object]) -> None:
    def unexpected_request(_: httpx.Request) -> httpx.Response:
        raise AssertionError("Bot API must not be called without configuration")

    publisher, http_client = make_publisher(
        httpx.MockTransport(unexpected_request),
        **overrides,
    )
    async with http_client:
        with pytest.raises(TelegramPublisherConfigurationError):
            await publisher.publish("Post")


@pytest.mark.asyncio
async def test_bot_api_maps_telegram_error() -> None:
    publisher, http_client = make_publisher(
        httpx.MockTransport(
            lambda _: httpx.Response(
                400,
                json={"ok": False, "description": "chat not found"},
            )
        )
    )
    async with http_client:
        with pytest.raises(TelegramPublishError, match="rejected"):
            await publisher.publish("Post")


@pytest.mark.asyncio
async def test_bot_api_maps_timeout() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out")

    publisher, http_client = make_publisher(httpx.MockTransport(handler))
    async with http_client:
        with pytest.raises(TelegramPublishError, match="request failed"):
            await publisher.publish("Post")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json={"ok": True, "result": {}}),
    ],
)
async def test_bot_api_rejects_malformed_response(response: httpx.Response) -> None:
    publisher, http_client = make_publisher(
        httpx.MockTransport(lambda _: response)
    )
    async with http_client:
        with pytest.raises(TelegramPublishError):
            await publisher.publish("Post")
