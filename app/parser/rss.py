"""Реализует получение и нормализацию RSS/Atom-лент.

Адаптер использует HTTP только для чтения источника и не зависит от ORM. Ошибка
отдельной записи пропускается, а фатальная ошибка ленты становится ``ParserError``.
"""

import calendar
import importlib
from datetime import UTC, datetime
from typing import Any

import httpx

from app.parser.base import ParsedNewsItem, ParserError, ParserSource

feedparser: Any = importlib.import_module("feedparser")


class RSSParser:
    """Получает RSS/Atom и возвращает единый список ``ParsedNewsItem``."""

    def __init__(
        self,
        *,
        max_items: int,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Настраивает лимит, timeout и необязательный HTTP-клиент для тестов."""
        self.max_items = max_items
        self.timeout = timeout
        self.client = client

    async def parse(self, source: ParserSource) -> list[ParsedNewsItem]:
        """Получает и разбирает одну RSS/Atom-ленту.

        Пустые и повреждённые элементы пропускаются независимо. Ошибка HTTP или
        полностью неразбираемая лента приводит к ``ParserError``.
        """
        try:
            if self.client is None:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    response = await client.get(source.url)
            else:
                response = await self.client.get(source.url, timeout=self.timeout, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ParserError("RSS source fetch failed") from error

        feed = feedparser.parse(response.content)
        entries = getattr(feed, "entries", [])
        if getattr(feed, "bozo", False) and not entries:
            raise ParserError("RSS payload could not be parsed")

        items: list[ParsedNewsItem] = []
        for entry in entries:
            if len(items) >= self.max_items:
                break
            try:
                title = str(entry.get("title", "")).strip()
                if not title:
                    continue
                items.append(
                    ParsedNewsItem(
                        title=title,
                        url=_optional_string(entry.get("link")),
                        summary=_optional_string(
                            entry.get("summary") or entry.get("description")
                        ),
                        published_at=_entry_datetime(entry),
                        external_id=_optional_string(entry.get("id") or entry.get("guid")),
                    )
                )
            except (TypeError, ValueError, OverflowError):
                continue
        return items


def _optional_string(value: object) -> str | None:
    """Нормализует необязательное значение feedparser до непустой строки."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _entry_datetime(entry: Any) -> datetime | None:
    """Преобразует дату RSS/Atom в timezone-aware UTC datetime."""
    value = entry.get("published_parsed") or entry.get("updated_parsed")
    if value is None:
        return None
    return datetime.fromtimestamp(calendar.timegm(value), tz=UTC)
