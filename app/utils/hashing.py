"""Содержит детерминированную нормализацию и SHA-256 дедупликацию новостей.

Контракт намеренно минимален: URL сохраняет query, но теряет fragment, а текст
сравнивается без учёта регистра и повторяющихся пробелов.
"""

import hashlib
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit


def normalize_url(url: str) -> str:
    """Применяет минимальный принятый контракт нормализации URL.

    Scheme и hostname приводятся к нижнему регистру, fragment удаляется, остальные
    части URL сохраняются для предсказуемой идентичности.
    """
    parsed = urlsplit(url.strip())
    hostname = (parsed.hostname or "").lower()
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    userinfo = parsed.netloc.rpartition("@")[0] + "@" if "@" in parsed.netloc else ""
    port = f":{parsed.port}" if parsed.port is not None else ""
    netloc = f"{userinfo}{hostname}{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, parsed.query, ""))


def content_hash(
    *,
    title: str,
    url: str | None,
    raw_text: str | None,
    published_at: datetime | None,
) -> str:
    """Возвращает детерминированный SHA-256 для дедупликации NewsItem.

    При наличии URL идентичность строится из URL и заголовка. Иначе используются
    заголовок, исходный текст и нормализованная дата публикации.
    """
    normalized_title = _normalize_text(title)
    if url:
        identity = f"url:{normalize_url(url)}\ntitle:{normalized_title}"
    else:
        published = _normalize_datetime(published_at)
        identity = (
            f"title:{normalized_title}\n"
            f"raw_text:{_normalize_text(raw_text or '')}\n"
            f"published_at:{published}"
        )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _normalize_text(value: str) -> str:
    """Схлопывает пробелы и приводит текст к регистронезависимому виду."""
    return " ".join(value.split()).casefold()


def _normalize_datetime(value: datetime | None) -> str:
    """Представляет необязательный datetime в стабильном UTC ISO-формате."""
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()
