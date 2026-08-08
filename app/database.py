"""Настраивает асинхронный слой доступа к PostgreSQL через SQLAlchemy.

Модуль создаёт общий engine, фабрику сессий и FastAPI dependency. Он не открывает
соединение при импорте и не определяет транзакционные границы успешных операций.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "dev",
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Объединяет metadata всех декларативных ORM-моделей приложения."""


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Передаёт запросу отдельную асинхронную SQLAlchemy-сессию.

    Успешный запрос не фиксируется автоматически. При исключении dependency
    откатывает незавершённую транзакцию, повторно выбрасывает ошибку и всегда
    закрывает сессию.
    """
    session = AsyncSessionLocal()
    try:
        yield session
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def dispose_engine() -> None:
    """Закрывает все соединения общего пула SQLAlchemy engine."""
    await engine.dispose()
