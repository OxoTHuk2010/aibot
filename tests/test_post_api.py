import asyncio
import importlib
import sys
from collections.abc import AsyncIterator, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import httpx
import pytest
from alembic.config import Config
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from alembic import command
from app.ai.client import AIConfigurationError, AIProviderError
from app.ai.generator import SourceMaterial
from app.publisher.telegram import (
    TelegramPublisherConfigurationError,
    TelegramPublishError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class FakeGenerator:
    def __init__(self) -> None:
        self.result = "Generated Telegram post 🚀"
        self.error: Exception | None = None
        self.calls: list[list[SourceMaterial]] = []

    async def generate(self, materials: Sequence[SourceMaterial]) -> str:
        self.calls.append(list(materials))
        if self.error is not None:
            raise self.error
        return self.result

    async def generate_from_text(self, text: str) -> str:
        self.calls.append([SourceMaterial(title="Manual test material", raw_text=text)])
        if self.error is not None:
            raise self.error
        return self.result


class FakePublisher:
    def __init__(self) -> None:
        self.message_id = 777
        self.error: Exception | None = None
        self.calls: list[str] = []

    async def publish(self, text: str) -> int:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.message_id


@dataclass
class ApiContext:
    client: httpx.AsyncClient
    session_factory: async_sessionmaker[AsyncSession]
    models: ModuleType
    generator: FakeGenerator
    publisher: FakePublisher


async def drop_alembic_version(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def post_app(database_url: str) -> Iterator[ModuleType]:
    module_names = (
        "app.main",
        "app.api.generate",
        "app.api.posts",
        "app.api.health",
        "app.api.sources",
        "app.api.keywords",
        "app.api.news",
        "app.services.post_service",
        "app.services.news_service",
        "app.services.source_service",
        "app.services.keyword_service",
        "app.schemas",
        "app.models",
        "app.database",
        "app.config",
    )
    for module_name in module_names:
        sys.modules.pop(module_name, None)

    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    command.upgrade(alembic_config, "head")
    for module_name in module_names:
        sys.modules.pop(module_name, None)

    module = importlib.import_module("app.main")
    yield module

    database = importlib.import_module("app.database")
    asyncio.run(database.dispose_engine())
    command.downgrade(alembic_config, "base")
    asyncio.run(drop_alembic_version(database_url))


@pytest.fixture
async def api(post_app: ModuleType, database_url: str) -> AsyncIterator[ApiContext]:
    database = importlib.import_module("app.database")
    models = importlib.import_module("app.models")
    generate_api = importlib.import_module("app.api.generate")
    posts_api = importlib.import_module("app.api.posts")
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    generator = FakeGenerator()
    publisher = FakePublisher()

    async def clean_tables() -> None:
        async with session_factory() as session:
            await session.execute(delete(models.Post))
            await session.execute(delete(models.NewsItem))
            await session.execute(delete(models.Keyword))
            await session.execute(delete(models.Source))
            await session.commit()

    async def override_session() -> AsyncIterator[AsyncSession]:
        session = session_factory()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    await clean_tables()
    post_app.app.dependency_overrides[database.get_session] = override_session
    post_app.app.dependency_overrides[generate_api.get_generator] = lambda: generator
    post_app.app.dependency_overrides[posts_api.get_publisher] = lambda: publisher
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=post_app.app),
        base_url="http://test",
    ) as client:
        yield ApiContext(client, session_factory, models, generator, publisher)
    post_app.app.dependency_overrides.clear()
    await clean_tables()
    await engine.dispose()


async def create_news(
    api: ApiContext,
    *statuses: str,
) -> list[int]:
    async with api.session_factory() as session:
        source = api.models.Source(
            name="CP4 source",
            source_type=api.models.SourceType.RSS,
            url="https://example.test/cp4",
        )
        session.add(source)
        await session.flush()
        news_items = [
            api.models.NewsItem(
                source_id=source.id,
                title=f"News {position}",
                summary=f"Summary {position}",
                raw_text=f"Raw text {position}",
                url=f"https://example.test/news/{position}",
                content_hash=f"{position:064x}",
                status=api.models.NewsItemStatus(status),
            )
            for position, status in enumerate(statuses, start=1)
        ]
        session.add_all(news_items)
        await session.commit()
        return [item.id for item in news_items]


@pytest.mark.asyncio
async def test_generate_post_one_many_associations_and_regeneration(api: ApiContext) -> None:
    first_id, second_id = await create_news(api, "new", "new")

    first = await api.client.post(
        "/api/generate",
        json={"news_ids": [second_id, first_id, second_id]},
    )
    repeated = await api.client.post(
        "/api/generate",
        json={"news_ids": [first_id, second_id]},
    )

    assert first.status_code == repeated.status_code == 201
    assert first.json()["id"] != repeated.json()["id"]
    assert set(first.json()["news_ids"]) == {first_id, second_id}
    assert [item.title for item in api.generator.calls[0]] == ["News 2", "News 1"]
    assert first.json()["generated_text"] == "Generated Telegram post 🚀"
    assert first.json()["status"] == "generated"
    assert first.json()["published_at"] is None
    assert first.json()["telegram_message_id"] is None

    async with api.session_factory() as session:
        posts = list(
            (
                await session.scalars(
                    select(api.models.Post).options(
                        selectinload(api.models.Post.news_items)
                    )
                )
            ).all()
        )
        assert len(posts) == 2
        assert all(post.generated_text for post in posts)
        assert all(len(post.news_items) == 2 for post in posts)


@pytest.mark.asyncio
async def test_generation_validation_and_provider_errors_do_not_create_post(
    api: ApiContext,
) -> None:
    new_id, filtered_id = await create_news(api, "new", "filtered")

    assert (await api.client.post("/api/generate", json={"news_ids": []})).status_code == 422
    missing = await api.client.post(
        "/api/generate",
        json={"news_ids": [new_id, 999999]},
    )
    filtered = await api.client.post(
        "/api/generate",
        json={"news_ids": [filtered_id]},
    )
    assert missing.status_code == 404
    assert filtered.status_code == 409

    api.generator.error = AIConfigurationError("secret provider detail")
    provider_error = await api.client.post(
        "/api/generate",
        json={"news_ids": [new_id]},
    )
    assert provider_error.status_code == 503
    assert provider_error.json() == {"detail": "AI generation is not configured"}
    assert "secret" not in provider_error.text

    async with api.session_factory() as session:
        assert await session.scalar(select(func.count(api.models.Post.id))) == 0


@pytest.mark.asyncio
async def test_generate_test_never_persists_post_and_maps_provider_failure(
    api: ApiContext,
) -> None:
    response = await api.client.post("/api/generate/test", json={"text": "Source facts"})

    assert response.status_code == 200
    assert response.json() == {"generated_text": "Generated Telegram post 🚀"}
    assert (await api.client.post("/api/generate/test", json={"text": "   "})).status_code == 422
    async with api.session_factory() as session:
        assert await session.scalar(select(func.count(api.models.Post.id))) == 0

    api.generator.error = AIProviderError("internal provider response")
    failed = await api.client.post("/api/generate/test", json={"text": "Source facts"})
    assert failed.status_code == 502
    assert "internal" not in failed.text


@pytest.mark.asyncio
async def test_post_read_api_filters_paginates_and_returns_detail(api: ApiContext) -> None:
    news_ids = await create_news(api, "new")
    first = (await api.client.post("/api/generate", json={"news_ids": news_ids})).json()
    second = (await api.client.post("/api/generate", json={"news_ids": news_ids})).json()

    listed = (await api.client.get("/api/posts", params={"status": "generated"})).json()
    page = (await api.client.get("/api/posts", params={"limit": 1, "offset": 1})).json()
    detail = await api.client.get(f"/api/posts/{first['id']}")

    assert [item["id"] for item in listed] == [second["id"], first["id"]]
    assert len(page) == 1
    assert detail.status_code == 200
    assert detail.json()["id"] == first["id"]
    assert (await api.client.get("/api/posts/999999")).status_code == 404
    assert (await api.client.get("/api/posts", params={"limit": 101})).status_code == 422


@pytest.mark.asyncio
async def test_publish_updates_post_and_repeated_publish_is_blocked(api: ApiContext) -> None:
    news_ids = await create_news(api, "new")
    generated = (await api.client.post("/api/generate", json={"news_ids": news_ids})).json()

    published = await api.client.post(f"/api/posts/{generated['id']}/publish")
    repeated = await api.client.post(f"/api/posts/{generated['id']}/publish")

    assert published.status_code == 200
    assert published.json()["status"] == "published"
    assert published.json()["telegram_message_id"] == 777
    assert published.json()["published_at"] is not None
    assert repeated.status_code == 409
    assert repeated.json() == {"detail": "Post is already published"}
    assert api.publisher.calls == ["Generated Telegram post 🚀"]
    published_list = (await api.client.get("/api/posts", params={"status": "published"})).json()
    assert [item["id"] for item in published_list] == [generated["id"]]

    async with api.session_factory() as session:
        news_item = await session.get(api.models.NewsItem, news_ids[0])
        assert news_item is not None
        assert news_item.status == api.models.NewsItemStatus.NEW


@pytest.mark.asyncio
async def test_publish_maps_missing_configuration_and_provider_failure(api: ApiContext) -> None:
    assert (await api.client.post("/api/posts/999999/publish")).status_code == 404
    news_ids = await create_news(api, "new")
    first = (await api.client.post("/api/generate", json={"news_ids": news_ids})).json()
    second = (await api.client.post("/api/generate", json={"news_ids": news_ids})).json()

    api.publisher.error = TelegramPublisherConfigurationError("secret configuration")
    not_configured = await api.client.post(f"/api/posts/{first['id']}/publish")
    assert not_configured.status_code == 503
    assert "secret" not in not_configured.text

    api.publisher.error = TelegramPublishError("provider internals")
    provider_failed = await api.client.post(f"/api/posts/{second['id']}/publish")
    assert provider_failed.status_code == 502
    assert "internals" not in provider_failed.text
    assert (await api.client.get(f"/api/posts/{second['id']}")).json()["status"] == "generated"
