from datetime import datetime
from uuid import UUID
from sqlalchemy import (String, Text, Boolean, DateTime, Integer, Index, UniqueConstraint, func, UUID)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base


class Source(Base):
    """Source model"""
    __tablename__ = 'sources'

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False) # [rss, htlm, telegram]
    url: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_parsed_at: Mapped[datetime] = mapped_column(DateTime,server_default=func.now(), server_onupdate=func.now())


class NewsItem(Base):
    """News item model"""
    __tablename__ = 'news'

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=True)
    summaty: Mapped[str] = mapped_column(String(100), nullable=True)
    raw_text: Mapped[str] = mapped_column(String, nullable=True)
    source_id: Mapped[UUID] = mapped_column(UUID, )
    content_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False) #  [new, filtered, generated, published, failed]
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Post(Base):
    """Post model"""
    __tablename__ = 'posts'

    id: Mapped[UUID] = mapped_column(UUID, primary_key=True)
    news_id: Mapped[UUID] = mapped_column(UUID, )
    generated_text: Mapped[str] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False) #  [generated, published, failed]
    error_message: Mapped[str] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    published_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

class Keyword(Base):
    """Keyword model"""
    __tablename__ = 'keywords'

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String(100), unique=True)
    type: Mapped[str] = mapped_column(String(10), default='include', index=True) # [include, exclude]
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
