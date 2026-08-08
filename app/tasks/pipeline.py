import logging
from dataclasses import asdict, dataclass

from sqlalchemy.exc import SQLAlchemyError

from app.ai.factory import create_generator
from app.config import settings
from app.database import AsyncSessionLocal, dispose_engine
from app.publisher.factory import create_publisher
from app.services.news_service import list_eligible_news_items, parse_source
from app.services.post_service import generate_post, publish_post
from app.services.source_service import list_enabled_sources

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class PipelineSummary:
    """JSON-serializable counters produced by one automatic pipeline run."""

    sources_total: int = 0
    sources_success: int = 0
    sources_failed: int = 0
    news_found: int = 0
    news_created: int = 0
    news_duplicates: int = 0
    news_filtered: int = 0
    news_selected: int = 0
    posts_generated: int = 0
    posts_published: int = 0
    generation_errors: int = 0
    publication_errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def build_batches(
    news_ids: list[int],
    *,
    news_per_post: int,
    max_posts: int,
) -> list[list[int]]:
    """Split the bounded FIFO selection into at most ``max_posts`` sequential batches."""
    if news_per_post < 1 or max_posts < 1:
        raise ValueError("batch limits must be at least 1")
    selected = news_ids[: news_per_post * max_posts]
    return [
        selected[offset : offset + news_per_post]
        for offset in range(0, len(selected), news_per_post)
    ]


async def run_pipeline_async() -> dict[str, int]:
    """Run one ingestion/generation/publication cycle with isolated partial failures."""
    summary = PipelineSummary()
    logger.info(
        "pipeline started",
        extra={"event": "pipeline_started", "auto_publish": settings.auto_publish},
    )
    try:
        async with AsyncSessionLocal() as session:
            sources = await list_enabled_sources(session)
        summary.sources_total = len(sources)

        for source in sources:
            logger.info(
                "source parsing started",
                extra={"event": "source_parsing_started", "source_id": source.id},
            )
            try:
                async with AsyncSessionLocal() as session:
                    result = await parse_source(session, source.id)
            except SQLAlchemyError:
                logger.exception(
                    "pipeline database failure during source parsing",
                    extra={"event": "pipeline_database_failed", "source_id": source.id},
                )
                raise
            # A source adapter is an isolation boundary; unknown adapter failures are partial.
            except Exception as error:  # noqa: BLE001
                summary.sources_failed += 1
                logger.error(
                    "source parsing failed",
                    extra={
                        "event": "source_parsing_failed",
                        "source_id": source.id,
                        "error_type": type(error).__name__,
                    },
                )
                continue

            summary.sources_success += 1
            summary.news_found += result.found
            summary.news_created += result.created
            summary.news_duplicates += result.duplicates
            summary.news_filtered += result.filtered
            logger.info(
                "source parsing completed",
                extra={
                    "event": "source_parsing_completed",
                    "source_id": source.id,
                    "news_created": result.created,
                },
            )

        selection_limit = (
            settings.pipeline_max_posts_per_run * settings.pipeline_news_per_post
        )
        async with AsyncSessionLocal() as session:
            eligible = await list_eligible_news_items(session, limit=selection_limit)
        summary.news_selected = len(eligible)
        logger.info(
            "eligible news selected",
            extra={"event": "eligible_news_selected", "count": len(eligible)},
        )

        batches = build_batches(
            [item.id for item in eligible],
            news_per_post=settings.pipeline_news_per_post,
            max_posts=settings.pipeline_max_posts_per_run,
        )
        if not batches:
            logger.info("pipeline completed: %s", summary.to_dict())
            return summary.to_dict()

        generator = create_generator(settings)
        publisher = create_publisher(settings) if settings.auto_publish else None
        for batch_index, news_ids in enumerate(batches, start=1):
            try:
                async with AsyncSessionLocal() as session:
                    post = await generate_post(session, news_ids, generator)
            except SQLAlchemyError:
                logger.exception(
                    "pipeline database failure during generation",
                    extra={"event": "pipeline_database_failed", "batch": batch_index},
                )
                raise
            # AI adapters expose typed errors, but a faulty batch must not stop later batches.
            except Exception as error:  # noqa: BLE001
                summary.generation_errors += 1
                logger.error(
                    "generation failed",
                    extra={
                        "event": "generation_failed",
                        "batch": batch_index,
                        "error_type": type(error).__name__,
                    },
                )
                continue

            summary.posts_generated += 1
            logger.info(
                "post generated",
                extra={"event": "post_generated", "post_id": post.id},
            )
            if publisher is None:
                continue

            try:
                # Safety boundary: AUTO_PUBLISH performs a real external Telegram send.
                async with AsyncSessionLocal() as session:
                    await publish_post(session, post.id, publisher)
            except SQLAlchemyError:
                logger.exception(
                    "pipeline database failure during publication",
                    extra={"event": "pipeline_database_failed", "post_id": post.id},
                )
                raise
            # Publication is a partial side effect; preserve generated Posts on any adapter error.
            except Exception as error:  # noqa: BLE001
                summary.publication_errors += 1
                logger.error(
                    "publication failed",
                    extra={
                        "event": "publication_failed",
                        "post_id": post.id,
                        "error_type": type(error).__name__,
                    },
                )
                continue

            summary.posts_published += 1
            logger.info(
                "post published",
                extra={"event": "post_published", "post_id": post.id},
            )

        logger.info("pipeline completed: %s", summary.to_dict())
        return summary.to_dict()
    finally:
        # A Celery worker invokes asyncio.run repeatedly; no asyncpg connection may cross loops.
        await dispose_engine()
