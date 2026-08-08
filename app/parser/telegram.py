import importlib
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from app.parser.base import (
    ParsedNewsItem,
    ParserConfigurationError,
    ParserError,
    ParserSource,
)


class TelegramParser:
    """Read recent text messages from one public Telegram channel through Telethon."""

    def __init__(
        self,
        *,
        api_id: int | None,
        api_hash: str | None,
        session_name: str,
        max_items: int,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.max_items = max_items
        self.client_factory = client_factory

    async def parse(self, source: ParserSource) -> list[ParsedNewsItem]:
        if self.api_id is None or not self.api_hash:
            raise ParserConfigurationError("Telegram API credentials are not configured")
        channel = _channel_from_url(source.url)
        factory = self.client_factory or importlib.import_module("telethon").TelegramClient

        try:
            client = factory(self.session_name, self.api_id, self.api_hash)
            connected = False
            try:
                await client.connect()
                connected = True
                if not await client.is_user_authorized():
                    raise ParserConfigurationError("Telegram session is not authorized")
                messages: AsyncIterator[Any] = client.iter_messages(
                    channel,
                    limit=self.max_items,
                )
                return [
                    item
                    async for message in messages
                    if (item := _message_to_item(message, channel)) is not None
                ]
            finally:
                if connected:
                    await client.disconnect()
        except ParserConfigurationError:
            raise
        except Exception as error:
            raise ParserError("Telegram source fetch failed") from error


def _channel_from_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ParserConfigurationError("Telegram source URL must use HTTP or HTTPS")
    if (parsed.hostname or "").lower() not in {"t.me", "www.t.me", "telegram.me"}:
        raise ParserConfigurationError("Telegram source URL must point to a public t.me channel")
    channel = parsed.path.strip("/").split("/", maxsplit=1)[0]
    if not channel or channel.startswith("+"):
        raise ParserConfigurationError("Telegram source must identify a public channel")
    return channel


def _message_to_item(message: Any, channel: str) -> ParsedNewsItem | None:
    raw_text = str(getattr(message, "message", None) or getattr(message, "raw_text", "")).strip()
    if not raw_text:
        return None
    message_id = getattr(message, "id", None)
    published_at = getattr(message, "date", None)
    if published_at is not None and not isinstance(published_at, datetime):
        published_at = None
    title = " ".join(raw_text.split())[:120]
    return ParsedNewsItem(
        title=title,
        url=f"https://t.me/{channel}/{message_id}" if message_id is not None else None,
        raw_text=raw_text,
        published_at=published_at,
        external_id=str(message_id) if message_id is not None else None,
    )
