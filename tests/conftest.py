import os

import pytest


@pytest.fixture(scope="session")
def database_url() -> str:
    """Возвращает PostgreSQL URL явно изолированного тестового окружения."""
    url = os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("DATABASE_URL must use the postgresql+asyncpg:// scheme")

    if os.getenv("APP_ENV") != "test":
        pytest.fail("PostgreSQL integration tests require APP_ENV=test")

    return url
