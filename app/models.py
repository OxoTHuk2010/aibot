"""Определяет ORM-модели и ограничения данных PostgreSQL.

Модуль хранит согласованный контракт Source, NewsItem, Post и Keyword. Связь
NewsItem--Post является M:N, а удаление одной стороны не удаляет другую.
"""

from datetime import datetime
from enum import Enum as PyEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy import (
    Enum as SqlEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def enum_values(enum_class: type[PyEnum]) -> list[str]:
    """Возвращает строковые значения enum для CHECK-ограничений PostgreSQL."""
    return [str(member.value) for member in enum_class]


class SourceType(str, PyEnum):
    """Перечисляет поддерживаемые способы получения новостей."""
    RSS = "rss"
    HTML = "html"
    TELEGRAM = "telegram"


class NewsItemStatus(str, PyEnum):
    """Отражает результат приёма и фильтрации новости."""
    NEW = "new"
    FILTERED = "filtered"
    FAILED = "failed"


class PostStatus(str, PyEnum):
    """Отражает lifecycle сгенерированного Telegram-поста."""
    GENERATED = "generated"
    PUBLISHED = "published"
    FAILED = "failed"


class KeywordType(str, PyEnum):
    """Определяет включающее или исключающее правило фильтрации."""
    INCLUDE = "include"
    EXCLUDE = "exclude"


post_news_items = Table(
    "post_news_items",
    Base.metadata,
    Column(
        "post_id",
        ForeignKey("posts.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "news_item_id",
        ForeignKey("news_items.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Source(Base):
    """Хранит RSS, HTML или Telegram-источник новостей.

    Source владеет своими NewsItem: физическое удаление источника каскадно удаляет
    собранные новости, а ``enabled=false`` только исключает его из сбора.
    """

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(
        SqlEnum(
            SourceType,
            name="source_type",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    last_parsed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    news_items: Mapped[list["NewsItem"]] = relationship(
        back_populates="source",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class NewsItem(Base):
    """Хранит нормализованную новость, полученную из одного Source.

    Уникальный SHA-256 ``content_hash`` является окончательной защитой от дублей.
    Связи с Post независимы от lifecycle самой новости.
    """

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[NewsItemStatus] = mapped_column(
        SqlEnum(
            NewsItemStatus,
            name="news_item_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=NewsItemStatus.NEW,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    source: Mapped[Source] = relationship(back_populates="news_items")
    posts: Mapped[list["Post"]] = relationship(
        secondary=post_news_items,
        back_populates="news_items",
        passive_deletes=True,
    )


class Post(Base):
    """Хранит AI-текст и состояние публикации Telegram-поста.

    Post может ссылаться на несколько NewsItem и не владеет ими. Идентификатор
    Telegram заполняется только после успешной внешней публикации.
    """

    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    generated_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[PostStatus] = mapped_column(
        SqlEnum(
            PostStatus,
            name="post_status",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=PostStatus.GENERATED,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        unique=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    news_items: Mapped[list[NewsItem]] = relationship(
        secondary=post_news_items,
        back_populates="posts",
        passive_deletes=True,
    )


class Keyword(Base):
    """Хранит включающее или исключающее правило фильтрации новостей.

    Нормализованное слово уникально глобально, а отключённые правила сохраняются,
    но не участвуют в принятии решения о статусе NewsItem.
    """

    __tablename__ = "keywords"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    type: Mapped[KeywordType] = mapped_column(
        SqlEnum(
            KeywordType,
            name="keyword_type",
            native_enum=False,
            create_constraint=True,
            values_callable=enum_values,
            validate_strings=True,
        ),
        default=KeywordType.INCLUDE,
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
