from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.keywords import router as keywords_router
from app.api.sources import router as sources_router
from app.config import settings
from app.database import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Release application resources during graceful shutdown."""
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    application = FastAPI(title=settings.app_name, lifespan=lifespan)
    application.include_router(health_router, prefix="/api")
    application.include_router(sources_router, prefix="/api")
    application.include_router(keywords_router, prefix="/api")
    return application


app = create_app()
