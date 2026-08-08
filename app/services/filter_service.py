from collections.abc import Iterable
from typing import Protocol

from app.models import KeywordType, NewsItemStatus
from app.parser.base import ParsedNewsItem


class KeywordLike(Protocol):
    word: str
    type: KeywordType
    enabled: bool


def determine_news_status(
    item: ParsedNewsItem,
    keywords: Iterable[KeywordLike],
) -> NewsItemStatus:
    """Apply the CP3 include/exclude substring rules to one parsed item."""
    text = " ".join(
        value for value in (item.title, item.summary, item.raw_text) if value
    ).casefold()
    enabled_keywords = [keyword for keyword in keywords if keyword.enabled]
    excludes = [keyword.word for keyword in enabled_keywords if keyword.type == KeywordType.EXCLUDE]
    if any(word in text for word in excludes):
        return NewsItemStatus.FILTERED

    includes = [keyword.word for keyword in enabled_keywords if keyword.type == KeywordType.INCLUDE]
    if not includes or any(word in text for word in includes):
        return NewsItemStatus.NEW
    return NewsItemStatus.FILTERED
