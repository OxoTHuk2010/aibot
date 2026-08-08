import json
from types import SimpleNamespace
from typing import Any, Self

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.schemas import ParseSourceResponse
from app.tasks import pipeline


class FakeSession:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.mark.parametrize(
    ("count", "news_per_post", "max_posts", "expected_sizes"),
    [
        (0, 5, 2, []),
        (1, 5, 2, [1]),
        (4, 5, 2, [4]),
        (5, 5, 2, [5]),
        (6, 5, 2, [5, 1]),
        (12, 5, 2, [5, 5]),
    ],
)
def test_build_batches_boundaries(
    count: int,
    news_per_post: int,
    max_posts: int,
    expected_sizes: list[int],
) -> None:
    batches = pipeline.build_batches(
        list(range(1, count + 1)),
        news_per_post=news_per_post,
        max_posts=max_posts,
    )

    assert [len(batch) for batch in batches] == expected_sizes
    assert [news_id for batch in batches for news_id in batch] == list(
        range(1, min(count, news_per_post * max_posts) + 1)
    )


@pytest.mark.parametrize(("news_per_post", "max_posts"), [(0, 1), (1, 0)])
def test_build_batches_rejects_invalid_limits(news_per_post: int, max_posts: int) -> None:
    with pytest.raises(ValueError):
        pipeline.build_batches(
            [1],
            news_per_post=news_per_post,
            max_posts=max_posts,
        )


@pytest.mark.asyncio
async def test_pipeline_generates_bounded_batches_without_auto_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = [SimpleNamespace(id=1), SimpleNamespace(id=2)]
    parse_calls: list[int] = []
    generation_calls: list[list[int]] = []
    disposed = False

    async def list_sources(_: FakeSession) -> list[Any]:
        return sources

    async def parse(_: FakeSession, source_id: int) -> ParseSourceResponse:
        parse_calls.append(source_id)
        return ParseSourceResponse(
            source_id=source_id,
            found=3,
            created=2,
            duplicates=1,
            filtered=1,
            errors=0,
        )

    async def select_news(_: FakeSession, *, limit: int) -> list[Any]:
        assert limit == 4
        return [SimpleNamespace(id=value) for value in range(1, 5)]

    async def generate(
        _: FakeSession,
        news_ids: list[int],
        generator: object,
    ) -> Any:
        assert generator == "generator"
        generation_calls.append(news_ids)
        return SimpleNamespace(id=len(generation_calls))

    async def dispose() -> None:
        nonlocal disposed
        disposed = True

    monkeypatch.setattr(pipeline, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(pipeline, "list_enabled_sources", list_sources)
    monkeypatch.setattr(pipeline, "parse_source", parse)
    monkeypatch.setattr(pipeline, "list_eligible_news_items", select_news)
    monkeypatch.setattr(pipeline, "generate_post", generate)
    monkeypatch.setattr(pipeline, "create_generator", lambda _: "generator")
    monkeypatch.setattr(
        pipeline,
        "create_publisher",
        lambda _: pytest.fail("publisher must not be built when AUTO_PUBLISH=false"),
    )
    monkeypatch.setattr(pipeline, "dispose_engine", dispose)
    monkeypatch.setattr(pipeline.settings, "auto_publish", False)
    monkeypatch.setattr(pipeline.settings, "pipeline_max_posts_per_run", 2)
    monkeypatch.setattr(pipeline.settings, "pipeline_news_per_post", 2)

    summary = await pipeline.run_pipeline_async()

    assert parse_calls == [1, 2]
    assert generation_calls == [[1, 2], [3, 4]]
    assert summary == {
        "sources_total": 2,
        "sources_success": 2,
        "sources_failed": 0,
        "news_found": 6,
        "news_created": 4,
        "news_duplicates": 2,
        "news_filtered": 2,
        "news_selected": 4,
        "posts_generated": 2,
        "posts_published": 0,
        "generation_errors": 0,
        "publication_errors": 0,
    }
    assert json.loads(json.dumps(summary)) == summary
    assert disposed is True


@pytest.mark.asyncio
async def test_pipeline_isolates_source_generation_and_publication_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generation_calls = 0
    publish_calls: list[int] = []

    async def list_sources(_: FakeSession) -> list[Any]:
        return [SimpleNamespace(id=1), SimpleNamespace(id=2)]

    async def parse(_: FakeSession, source_id: int) -> ParseSourceResponse:
        if source_id == 1:
            raise RuntimeError("source failed")
        return ParseSourceResponse(
            source_id=source_id,
            found=2,
            created=2,
            duplicates=0,
            filtered=0,
            errors=0,
        )

    async def select_news(_: FakeSession, *, limit: int) -> list[Any]:
        assert limit == 4
        return [SimpleNamespace(id=value) for value in range(1, 5)]

    async def generate(
        _: FakeSession,
        news_ids: list[int],
        generator: object,
    ) -> Any:
        nonlocal generation_calls
        generation_calls += 1
        if generation_calls == 1:
            raise RuntimeError("AI failed")
        assert news_ids == [3, 4]
        return SimpleNamespace(id=99)

    async def publish(
        _: FakeSession,
        post_id: int,
        publisher: object,
    ) -> None:
        assert publisher == "publisher"
        publish_calls.append(post_id)
        raise RuntimeError("Telegram failed")

    async def dispose() -> None:
        return None

    monkeypatch.setattr(pipeline, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(pipeline, "list_enabled_sources", list_sources)
    monkeypatch.setattr(pipeline, "parse_source", parse)
    monkeypatch.setattr(pipeline, "list_eligible_news_items", select_news)
    monkeypatch.setattr(pipeline, "generate_post", generate)
    monkeypatch.setattr(pipeline, "publish_post", publish)
    monkeypatch.setattr(pipeline, "create_generator", lambda _: "generator")
    monkeypatch.setattr(pipeline, "create_publisher", lambda _: "publisher")
    monkeypatch.setattr(pipeline, "dispose_engine", dispose)
    monkeypatch.setattr(pipeline.settings, "auto_publish", True)
    monkeypatch.setattr(pipeline.settings, "pipeline_max_posts_per_run", 2)
    monkeypatch.setattr(pipeline.settings, "pipeline_news_per_post", 2)

    summary = await pipeline.run_pipeline_async()

    assert generation_calls == 2
    assert publish_calls == [99]
    assert summary["sources_success"] == 1
    assert summary["sources_failed"] == 1
    assert summary["posts_generated"] == 1
    assert summary["posts_published"] == 0
    assert summary["generation_errors"] == 1
    assert summary["publication_errors"] == 1


@pytest.mark.asyncio
async def test_empty_pipeline_does_not_build_external_backends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_sources(_: FakeSession) -> list[Any]:
        return []

    async def no_news(_: FakeSession, *, limit: int) -> list[Any]:
        assert limit > 0
        return []

    disposed = False

    async def dispose() -> None:
        nonlocal disposed
        disposed = True

    monkeypatch.setattr(pipeline, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(pipeline, "list_enabled_sources", no_sources)
    monkeypatch.setattr(pipeline, "list_eligible_news_items", no_news)
    monkeypatch.setattr(
        pipeline,
        "create_generator",
        lambda _: pytest.fail("AI must not be configured without eligible news"),
    )
    monkeypatch.setattr(pipeline, "dispose_engine", dispose)

    summary = await pipeline.run_pipeline_async()

    assert summary["news_selected"] == 0
    assert summary["posts_generated"] == 0
    assert disposed is True


@pytest.mark.asyncio
async def test_database_failure_fails_pipeline_and_disposes_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disposed = False

    async def database_failure(_: FakeSession) -> list[Any]:
        raise SQLAlchemyError("database unavailable")

    async def dispose() -> None:
        nonlocal disposed
        disposed = True

    monkeypatch.setattr(pipeline, "AsyncSessionLocal", FakeSession)
    monkeypatch.setattr(pipeline, "list_enabled_sources", database_failure)
    monkeypatch.setattr(pipeline, "dispose_engine", dispose)

    with pytest.raises(SQLAlchemyError, match="database unavailable"):
        await pipeline.run_pipeline_async()
    assert disposed is True
