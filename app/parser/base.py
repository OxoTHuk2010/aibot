from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.config import Settings
    from app.models import SourceType


@dataclass(frozen=True, slots=True)
class ParsedNewsItem:
    """Framework-independent normalized output produced by every parser."""

    title: str
    url: str | None = None
    summary: str | None = None
    raw_text: str | None = None
    published_at: datetime | None = None
    external_id: str | None = None


class ParserSource(Protocol):
    url: str
    name: str


class NewsParser(Protocol):
    async def parse(self, source: ParserSource) -> list[ParsedNewsItem]: ...


class ParserError(Exception):
    """An external source could not be fetched or parsed."""


class ParserConfigurationError(ParserError):
    """A parser-specific optional integration is not configured."""


class UnsupportedSourceTypeError(ParserError):
    """No parser exists for the requested source type."""


def create_parser(source_type: "SourceType", app_settings: "Settings") -> NewsParser:
    """Create the parser for one supported SourceType without a registry framework."""
    from app.parser.html import HTMLParser
    from app.parser.rss import RSSParser
    from app.parser.telegram import TelegramParser

    source_type_value = getattr(source_type, "value", source_type)
    if source_type_value == "rss":
        return RSSParser(max_items=app_settings.max_news_per_source)
    if source_type_value == "html":
        return HTMLParser(max_items=app_settings.max_news_per_source)
    if source_type_value == "telegram":
        api_hash = (
            app_settings.telegram_api_hash.get_secret_value()
            if app_settings.telegram_api_hash is not None
            else None
        )
        return TelegramParser(
            api_id=app_settings.telegram_api_id,
            api_hash=api_hash,
            session_name=app_settings.telegram_session_name,
            max_items=app_settings.max_news_per_source,
        )
    raise UnsupportedSourceTypeError(f"Unsupported source type: {source_type_value}")
