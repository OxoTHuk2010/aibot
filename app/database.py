from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo={settings.app_env == 'dev'},
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

async def get_session() -> AsyncSession:
    """Функция для получения сессии"""
    async with AsyncSessionLocal() as session:
        yield session
