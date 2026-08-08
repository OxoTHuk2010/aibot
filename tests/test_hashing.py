from datetime import UTC, datetime

from app.utils.hashing import content_hash, normalize_url


def make_hash(*, title: str = "Title", url: str | None = None) -> str:
    return content_hash(
        title=title,
        url=url,
        raw_text="Body",
        published_at=datetime(2025, 8, 8, tzinfo=UTC),
    )


def test_content_hash_is_deterministic_sha256() -> None:
    first = make_hash(url="HTTPS://Example.COM/story")
    second = make_hash(url="HTTPS://Example.COM/story")

    assert first == second
    assert len(first) == 64


def test_different_identity_produces_different_hash() -> None:
    assert make_hash(title="First") != make_hash(title="Second")


def test_url_fragment_does_not_affect_hash() -> None:
    with_fragment = make_hash(url="https://example.com/story#section")
    without_fragment = make_hash(url="https://example.com/story")

    assert with_fragment == without_fragment


def test_url_normalization_lowercases_scheme_and_host_only() -> None:
    assert normalize_url(" HTTPS://User@Example.COM:8443/path?q=One#part ") == (
        "https://User@example.com:8443/path?q=One"
    )


def test_hash_without_url_uses_text_and_published_at() -> None:
    first = content_hash(
        title="Story",
        url=None,
        raw_text="First body",
        published_at=datetime(2025, 8, 8, tzinfo=UTC),
    )
    second = content_hash(
        title="Story",
        url=None,
        raw_text="Second body",
        published_at=datetime(2025, 8, 8, tzinfo=UTC),
    )

    assert first != second
