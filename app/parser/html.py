"""Реализует демонстрационный parser списков HTML-статей.

Поддерживается простой профиль на основе элементов ``article``; универсального
selector DSL модуль не предоставляет. Отдельная повреждённая статья пропускается.
"""

from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app.parser.base import ParsedNewsItem, ParserError, ParserSource

USER_AGENT = "aibot-learning-mvp/0.1"


class HTMLParser:
    """Разбирает простую HTML-страницу по встроенному учебному профилю."""

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
        """Получает HTML и нормализует распознанные элементы ``article``.

        Ошибка получения страницы становится ``ParserError``. Некорректная
        отдельная статья не останавливает обработку остальных элементов.
        """
        headers = {"User-Agent": USER_AGENT}
        try:
            if self.client is None:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                    response = await client.get(source.url, headers=headers)
            else:
                response = await self.client.get(
                    source.url,
                    headers=headers,
                    timeout=self.timeout,
                    follow_redirects=True,
                )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise ParserError("HTML source fetch failed") from error

        soup = BeautifulSoup(response.text, "html.parser")
        items: list[ParsedNewsItem] = []
        for article in soup.select("article"):
            if len(items) >= self.max_items:
                break
            parsed = _parse_article(article, source.url)
            if parsed is not None:
                items.append(parsed)
        return items


def _parse_article(article: Tag, base_url: str) -> ParsedNewsItem | None:
    """Преобразует один HTML-элемент article в нормализованную новость.

    Относительные ссылки разрешаются от URL источника. Если обязательный заголовок
    отсутствует или элемент повреждён, функция возвращает ``None``.
    """
    try:
        title_node = article.select_one("h1, h2, h3")
        if title_node is None:
            return None
        title = title_node.get_text(" ", strip=True)
        if not title:
            return None

        link_node = article.select_one("a[href]")
        href = link_node.get("href") if link_node is not None else None
        url = urljoin(base_url, str(href).strip()) if href else None

        summary_node = article.select_one(".summary, .description, p")
        summary = summary_node.get_text(" ", strip=True) if summary_node is not None else None

        time_node = article.select_one("time[datetime]")
        published_at = _parse_datetime(time_node.get("datetime") if time_node else None)
        return ParsedNewsItem(
            title=title,
            url=url,
            summary=summary or None,
            raw_text=summary or None,
            published_at=published_at,
        )
    except (AttributeError, TypeError, ValueError):
        return None


def _parse_datetime(value: object) -> datetime | None:
    """Разбирает ISO datetime и добавляет UTC для значения без timezone."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(str(value).strip())
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
