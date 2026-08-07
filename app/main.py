from fastapi import FastAPI
from config import settings
from app.api.health import router as health_router

def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
    )
    app.include_router(health_router, prefix='/api')
    return app