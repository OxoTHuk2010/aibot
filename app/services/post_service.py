from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.ai.generator import SourceMaterial
from app.models import NewsItem, NewsItemStatus, Post, PostStatus


class PostNotFoundError(Exception):
    """The requested post does not exist."""


class NewsItemsNotFoundError(Exception):
    """At least one requested news item does not exist."""

    def __init__(self, news_ids: Sequence[int]) -> None:
        self.news_ids = list(news_ids)
        super().__init__("Requested news items were not found")


class InvalidNewsItemStateError(Exception):
    """At least one news item is not eligible for generation."""

    def __init__(self, news_ids: Sequence[int]) -> None:
        self.news_ids = list(news_ids)
        super().__init__("Only news items with status=new can be generated")


class PostAlreadyPublishedError(Exception):
    """A published post must not be sent again."""


class PostNotPublishableError(Exception):
    """The post has no generated content eligible for publication."""


class GeneratorLike(Protocol):
    async def generate(self, materials: Sequence[SourceMaterial]) -> str: ...


class PublisherLike(Protocol):
    async def publish(self, text: str) -> int: ...


async def generate_post(
    session: AsyncSession,
    news_ids: Sequence[int],
    generator: GeneratorLike,
) -> Post:
    """Generate and persist a Post linked to all requested eligible news items."""
    ordered_ids = list(dict.fromkeys(news_ids))
    statement = (
        select(NewsItem)
        .options(selectinload(NewsItem.source))
        .where(NewsItem.id.in_(ordered_ids))
    )
    found = list((await session.scalars(statement)).all())
    by_id = {item.id: item for item in found}
    missing = [news_id for news_id in ordered_ids if news_id not in by_id]
    if missing:
        await session.rollback()
        raise NewsItemsNotFoundError(missing)

    news_items = [by_id[news_id] for news_id in ordered_ids]
    invalid = [item.id for item in news_items if item.status != NewsItemStatus.NEW]
    if invalid:
        await session.rollback()
        raise InvalidNewsItemStateError(invalid)

    materials = [
        SourceMaterial(
            title=item.title,
            summary=item.summary,
            raw_text=item.raw_text,
            url=item.url,
            source_name=item.source.name,
        )
        for item in news_items
    ]
    try:
        generated_text = await generator.generate(materials)
        post = Post(
            generated_text=generated_text,
            status=PostStatus.GENERATED,
            published_at=None,
            telegram_message_id=None,
            news_items=news_items,
        )
        session.add(post)
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_post(session, post.id)


async def get_post(session: AsyncSession, post_id: int) -> Post:
    statement = (
        select(Post)
        .options(selectinload(Post.news_items))
        .where(Post.id == post_id)
    )
    post = (await session.scalars(statement)).one_or_none()
    if post is None:
        raise PostNotFoundError
    return post


async def list_posts(
    session: AsyncSession,
    *,
    status: PostStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Post]:
    statement = select(Post).options(selectinload(Post.news_items))
    if status is not None:
        statement = statement.where(Post.status == status)
    statement = statement.order_by(Post.created_at.desc(), Post.id.desc())
    statement = statement.limit(limit).offset(offset)
    return list((await session.scalars(statement)).all())


async def publish_post(
    session: AsyncSession,
    post_id: int,
    publisher: PublisherLike,
) -> Post:
    """Publish one generated Post and persist the Telegram delivery result."""
    statement = (
        select(Post)
        .options(selectinload(Post.news_items))
        .where(Post.id == post_id)
        .with_for_update()
    )
    post = (await session.scalars(statement)).one_or_none()
    if post is None:
        await session.rollback()
        raise PostNotFoundError
    if post.status == PostStatus.PUBLISHED:
        await session.rollback()
        raise PostAlreadyPublishedError
    if post.status != PostStatus.GENERATED or not post.generated_text.strip():
        await session.rollback()
        raise PostNotPublishableError

    try:
        message_id = await publisher.publish(post.generated_text)
        post.status = PostStatus.PUBLISHED
        post.published_at = datetime.now(UTC)
        post.telegram_message_id = message_id
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    return await get_post(session, post.id)
