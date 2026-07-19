from datetime import datetime
from uuid import UUID
from sqlalchemy import (String, Text, Boolean, DateTime, Integer, Index, UniqueConstraint, func, UUID, ForeignKey)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from enum import Enum as PyEnum


class NewsItemStatus(str, PyEnum):
    """Enumeration of possible statuses for a news item throughout its lifecycle.

    Attributes:
        NEW: News item has been ingested but not yet processed.
        FILTERED: News item has passed through keyword filtering.
        GENERATED: A post has been generated from this news item.
        PUBLISHED: The generated post has been published.
        FAILED: Processing or publishing of this news item failed.
    """
    NEW = 'new'
    FILTERED = 'filtered'
    GENERATED = 'generated'
    PUBLISHED = 'published'
    FAILED = 'failed'

class PostStatus(str, PyEnum):
    """Enumeration of possible statuses for a generated post.

    Attributes:
        GENERATED: The post text has been generated from a news item.
        PUBLISHED: The post has been successfully published to the target channel.
        FAILED: Post generation or publishing failed.
    """
    GENERATED = 'generated'
    PUBLISHED = 'published'
    FAILED = 'failed'

class KeywordType(str, PyEnum):
    """Enumeration of keyword filtering types.

    Attributes:
        INCLUDE: Keyword used to include matching news items.
        EXCLUDE: Keyword used to exclude matching news items.
    """
    INCLUDE = 'include'
    EXCLUDE = 'exclude'


class Source(Base):
    """Represents a content source (RSS feed, HTML page, or Telegram channel) from which news items are parsed.

    Attributes:
        id: Unique identifier for the source.
        name: Human-readable name of the source.
        source_type: Type of the source — one of 'rss', 'html', or 'telegram'.
        url: URL of the source. Must be unique across all sources.
        enabled: Whether the source is active and should be parsed.
        created_at: Timestamp when the source was created.
        last_parsed_at: Timestamp of the last successful parse attempt.

    Relationships:
        news_items: Collection of NewsItem instances parsed from this source.
    """
    __tablename__ = 'sources'

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False) # [rss, htlm, telegram]
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_parsed_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.now(), server_onupdate=func.now())

    news_items: Mapped[list['NewsItem']] = relationship(back_populates='source')


class NewsItem(Base):
    """Represents a single news item parsed from a Source.

    Stores the raw content, a generated summary, and tracks the processing
    status through the pipeline (new → filtered → generated → published/failed).

    Attributes:
        id: Unique identifier for the news item.
        title: Headline or title of the news item.
        url: Direct link to the original article (optional).
        summary: Short summary or excerpt of the news item (optional).
        raw_text: Full raw text content of the news item (optional).
        source_id: Foreign key referencing the Source this item belongs to.
        content_hash: Unique hash of the content for deduplication. Indexed.
        status: Current NewsItemStatus in the processing pipeline. Indexed.
        created_at: Timestamp when the news item was created.

    Relationships:
        source: The Source from which this news item was parsed.
        posts: The Post generated from this news item (one-to-one).
    """
    __tablename__ = 'news'

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str|None] = mapped_column(String(500), nullable=True)
    summary: Mapped[str|None] = mapped_column(String(100), nullable=True)
    raw_text: Mapped[str|None] = mapped_column(String, nullable=True)
    source_id: Mapped[UUID] = mapped_column(ForeignKey('sources.id'), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    status: Mapped[NewsItemStatus] = mapped_column(String(20), default=NewsItemStatus.NEW, nullable=False, index=True) #NewsItemStatus
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    source: Mapped['Source'] = relationship(back_populates='news_items')
    posts: Mapped['Post'] = relationship(back_populates='news')

    __table_args__ = (
        Index('ix_news_unprocessed_recent', 'content_hash', 'status'),
        )

class Post(Base):
    """Represents a generated post ready for publishing.

    Stores the AI-generated text derived from a NewsItem and tracks its
    publishing status.

    Attributes:
        id: Unique identifier for the post.
        news_id: Foreign key referencing the source NewsItem.
        generated_text: The AI-generated post content (optional).
        status: Current PostStatus — generated, published, or failed.
        error_message: Error details if generation or publishing failed (optional).
        created_at: Timestamp when the post was created.
        published_at: Timestamp when the post was successfully published.

    Relationships:
        news: The NewsItem from which this post was generated.
    """
    __tablename__ = 'posts'

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True)
    news_id: Mapped[UUID] = mapped_column(ForeignKey('news.id'), nullable=False, index=True)
    generated_text: Mapped[str|None] = mapped_column(Text, nullable=True)
    status: Mapped[PostStatus] = mapped_column(String(20), default=PostStatus.GENERATED, nullable=False) #PostStatus
    error_message: Mapped[str|None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    published_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    news: Mapped['NewsItem'] = relationship(back_populates='posts')

class Keyword(Base):
    """Represents a keyword used for filtering news items.

    Keywords can be either inclusive (keep matching items) or exclusive
    (discard matching items), and can be toggled on/off without deletion.

    Attributes:
        id: Auto-incrementing primary key.
        word: The keyword text. Must be unique.
        type: Whether this is an include or exclude keyword.
        enabled: Whether this keyword is currently active for filtering.
    """
    __tablename__ = 'keywords'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String(100), unique=True)
    type: Mapped[KeywordType] = mapped_column(String(10), default=KeywordType.INCLUDE, nullable=False) #KeywordType
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

