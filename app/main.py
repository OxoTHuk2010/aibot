"""Создаёт и настраивает HTTP-приложение FastAPI.

Модуль объединяет маршруты прикладных API и управляет общим lifecycle ресурсов.
Запуск не проверяет внешние сервисы, а завершение освобождает пул PostgreSQL.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.generate import router as generate_router
from app.api.health import router as health_router
from app.api.keywords import router as keywords_router
from app.api.news import router as news_router
from app.api.posts import router as posts_router
from app.api.sources import router as sources_router
from app.config import settings
from app.database import dispose_engine

OPENAPI_TAGS = [
    {"name": "Health", "description": "Проверка работоспособности процесса приложения."},
    {"name": "Sources", "description": "Управление источниками и ручной сбор новостей."},
    {"name": "Keywords", "description": "Управление правилами включения и исключения новостей."},
    {"name": "News", "description": "Чтение собранных и отфильтрованных новостей."},
    {"name": "Generation", "description": "Генерация текста постов через выбранный AI-провайдер."},
    {"name": "Posts", "description": "Чтение и публикация подготовленных Telegram-постов."},
]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Управляет ресурсами на протяжении жизни HTTP-приложения.

    На старте функция намеренно не обращается к внешним сервисам. При штатном
    завершении она освобождает соединения общего SQLAlchemy engine.
    """
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    """Создаёт FastAPI-приложение с публичными маршрутами CP1--CP5.

    Функция сохраняет стандартные адреса Swagger UI и OpenAPI и не выполняет
    сетевых проверок при построении объекта приложения.
    """
    application = FastAPI(
        title=settings.app_name,
        description=(
            "Учебный API для сбора новостей, AI-генерации постов и публикации "
            "в Telegram. Внешние интеграции настраиваются независимо и могут "
            "быть недоступны без нарушения process liveness."
        ),
        version="1.0.0",
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )
    application.include_router(health_router, prefix="/api")
    application.include_router(sources_router, prefix="/api")
    application.include_router(keywords_router, prefix="/api")
    application.include_router(news_router, prefix="/api")
    application.include_router(generate_router, prefix="/api")
    application.include_router(posts_router, prefix="/api")
    return application


app = create_app()
