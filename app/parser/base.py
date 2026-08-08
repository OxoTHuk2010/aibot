"""Задаёт единый контракт parser layer и нормализованный результат разбора.

Parser получает данные внешнего источника, но не работает с PostgreSQL. Фабрика
выбирает конкретный адаптер по принятому ``SourceType`` без plugin framework.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.config import Settings
    from app.models import SourceType


@dataclass(frozen=True, slots=True)
class ParsedNewsItem:
    """Представляет единый независимый от ORM результат любого parser.

    Обязателен только заголовок; прочие поля сохраняют доступные исходные данные
    и окончательно нормализуются сервисом ingestion перед записью.
    """

    title: str
    url: str | None = None
    summary: str | None = None
    raw_text: str | None = None
    published_at: datetime | None = None
    external_id: str | None = None


class ParserSource(Protocol):
    """Описывает минимальные поля источника, необходимые parser."""

    url: str
    name: str


class NewsParser(Protocol):
    """Задаёт общий асинхронный контракт получения нормализованных новостей."""

    async def parse(self, source: ParserSource) -> list[ParsedNewsItem]:
        """Получает данные одного источника без записи в базу данных."""
        ...


class ParserError(Exception):
    """Сообщает, что внешний источник не удалось получить или разобрать."""


class ParserConfigurationError(ParserError):
    """Сообщает об отсутствии обязательной настройки выбранного parser."""


class UnsupportedSourceTypeError(ParserError):
    """Сообщает, что для типа источника не существует parser."""


def create_parser(source_type: "SourceType", app_settings: "Settings") -> NewsParser:
    """Создаёт parser для одного поддерживаемого ``SourceType``.

    Telegram credentials извлекаются только при выборе TelegramParser. Для
    неизвестного типа функция выбрасывает ``UnsupportedSourceTypeError``.
    """
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
