from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from typing import AsyncGenerator
from contextlib import asynccontextmanager

from app.config import settings

is_dev = settings.app_env == 'dev'

engine = create_async_engine(
    settings.database_url,
    echo=is_dev,
    pool_size = 10,
    max_overflow = 20,
    pool_pre_ping = True
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_= AsyncSession,
    expire_on_commit=False
)

class Base(DeclarativeBase):
    """Базовый класс для моделей"""
    pass

@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Фабрика-контекстный менеджер. Автоматически закроет сессию."""
    # async with сам поймает исключения и закроет сессию корректно
    async with AsyncSessionLocal() as session:
        yield session
    

async def dispose_engine() -> None:
    await engine.dispose()