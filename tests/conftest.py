import os

import pytest


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """Return the explicitly configured PostgreSQL integration-test URL."""
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail("TEST_DATABASE_URL must use the postgresql+asyncpg:// scheme")

    application_url = os.getenv("DATABASE_URL")
    if application_url and application_url == url:
        pytest.fail("TEST_DATABASE_URL must not be the application DATABASE_URL")

    return url
