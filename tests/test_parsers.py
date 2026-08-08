from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from app.parser.base import ParserConfigurationError, ParserError
from app.parser.html import USER_AGENT, HTMLParser
from app.parser.rss import RSSParser
from app.parser.telegram import TelegramParser

FIXTURES = Path(__file__).with_name("fixtures")


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def source(url: str) -> Any:
    return SimpleNamespace(url=url, name="Fixture source")


@pytest.mark.asyncio
async def test_rss_parser_normalizes_entries_and_optional_fields() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=fixture_bytes("sample_feed.xml"), request=request)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        items = await RSSParser(max_items=10, client=client).parse(source("https://feed.test/rss"))

    assert [item.title for item in items] == [
        "First story",
        "Title without optional fields",
        "Third valid story",
    ]
    assert items[0].external_id == "story-1"
    assert items[0].published_at == datetime(2025, 8, 8, 10, tzinfo=UTC)
    assert items[1].url is None
    assert items[1].summary is None


@pytest.mark.asyncio
async def test_rss_parser_enforces_valid_item_limit() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=fixture_bytes("sample_feed.xml"), request=request)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        items = await RSSParser(max_items=2, client=client).parse(source("https://feed.test/rss"))

    assert len(items) == 2


@pytest.mark.asyncio
async def test_rss_parser_maps_fetch_and_malformed_payload_errors() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("fixture timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as client:
        with pytest.raises(ParserError):
            await RSSParser(max_items=10, client=client).parse(source("https://feed.test/rss"))

    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"not a feed", request=request)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ParserError):
            await RSSParser(max_items=10, client=client).parse(source("https://feed.test/rss"))


@pytest.mark.asyncio
async def test_html_parser_extracts_articles_and_relative_urls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["User-Agent"] == USER_AGENT
        return httpx.Response(200, content=fixture_bytes("sample_page.html"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        items = await HTMLParser(max_items=10, client=client).parse(
            source("https://site.test/news/")
        )

    assert [item.title for item in items] == ["First HTML story", "Second HTML story"]
    assert items[0].url == "https://site.test/articles/first"
    assert items[0].summary == "First HTML summary"
    assert items[0].published_at == datetime(2025, 8, 8, 10, tzinfo=UTC)
    assert items[1].summary is None


@pytest.mark.asyncio
async def test_html_parser_enforces_limit() -> None:
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=fixture_bytes("sample_page.html"), request=request)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        items = await HTMLParser(max_items=1, client=client).parse(source("https://site.test"))

    assert len(items) == 1


class FakeTelegramClient:
    last_channel: str | None = None
    last_limit: int | None = None

    def __init__(self, *_: object) -> None:
        self.messages = [
            SimpleNamespace(id=12, message="Telegram story body", date=datetime(2025, 8, 8, tzinfo=UTC)),
            SimpleNamespace(id=11, message="", date=datetime(2025, 8, 7, tzinfo=UTC)),
        ]

    authorized = True

    async def connect(self) -> None:
        return None

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def disconnect(self) -> None:
        return None

    async def iter_messages(self, channel: str, *, limit: int) -> Any:
        self.__class__.last_channel = channel
        self.__class__.last_limit = limit
        for message in self.messages[:limit]:
            yield message


@pytest.mark.asyncio
async def test_telegram_parser_converts_messages_without_network() -> None:
    parser = TelegramParser(
        api_id=123,
        api_hash="test-hash",
        session_name="test",
        max_items=2,
        client_factory=FakeTelegramClient,
    )

    items = await parser.parse(source("https://t.me/example_channel"))

    assert len(items) == 1
    assert items[0].external_id == "12"
    assert items[0].published_at == datetime(2025, 8, 8, tzinfo=UTC)
    assert items[0].raw_text == "Telegram story body"
    assert FakeTelegramClient.last_channel == "example_channel"
    assert FakeTelegramClient.last_limit == 2


@pytest.mark.asyncio
async def test_telegram_parser_requires_optional_credentials() -> None:
    parser = TelegramParser(
        api_id=None,
        api_hash=None,
        session_name="test",
        max_items=10,
        client_factory=FakeTelegramClient,
    )

    with pytest.raises(ParserConfigurationError):
        await parser.parse(source("https://t.me/example_channel"))


@pytest.mark.asyncio
async def test_telegram_parser_requires_prepared_authorized_session() -> None:
    class UnauthorizedClient(FakeTelegramClient):
        authorized = False

    parser = TelegramParser(
        api_id=123,
        api_hash="test-hash",
        session_name="test",
        max_items=10,
        client_factory=UnauthorizedClient,
    )

    with pytest.raises(ParserConfigurationError):
        await parser.parse(source("https://t.me/example_channel"))
