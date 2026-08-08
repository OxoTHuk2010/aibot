import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ASYNC_DATABASE_URL = "postgresql+asyncpg://test:test@127.0.0.1:5432/test"
RABBITMQ_URL = "amqp://test:test@127.0.0.1:5672//"


@pytest.fixture
def celery_module(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> ModuleType:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", ASYNC_DATABASE_URL)
    monkeypatch.setenv("RABBITMQ_URL", RABBITMQ_URL)
    monkeypatch.setenv("APP_ENV", "test")
    for name in (
        "app.tasks.celery_app",
        "app.tasks.pipeline",
        "app.database",
        "app.config",
    ):
        sys.modules.pop(name, None)
    return importlib.import_module("app.tasks.celery_app")


def test_celery_uses_rabbitmq_json_utc_and_no_result_backend(
    celery_module: ModuleType,
) -> None:
    app = celery_module.celery_app

    assert app.conf.broker_url == RABBITMQ_URL
    assert app.conf.result_backend is None
    assert app.conf.task_serializer == "json"
    assert app.conf.accept_content == ["json"]
    assert app.conf.timezone == "UTC"
    assert app.conf.enable_utc is True
    assert app.conf.task_acks_late is False
    assert app.conf.worker_prefetch_multiplier == 1


def test_celery_registers_one_pipeline_task_and_half_hour_schedule(
    celery_module: ModuleType,
) -> None:
    app = celery_module.celery_app
    schedule = app.conf.beat_schedule["run-pipeline-every-30-minutes"]

    assert "app.tasks.run_pipeline" in app.tasks
    assert schedule["task"] == "app.tasks.run_pipeline"
    assert schedule["schedule"].minute == {0, 30}
    assert schedule["schedule"].hour == set(range(24))


def test_celery_configuration_requires_rabbitmq_url(
    celery_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(celery_module, "settings", SimpleNamespace(rabbitmq_url=None))

    with pytest.raises(celery_module.CeleryConfigurationError, match="RABBITMQ_URL"):
        celery_module.create_celery_app()


def test_sync_task_runs_one_async_pipeline(
    celery_module: ModuleType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_pipeline() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"posts_generated": 1}

    monkeypatch.setattr(celery_module, "run_pipeline_async", fake_pipeline)

    assert celery_module.run_pipeline.run() == {"posts_generated": 1}
    assert calls == 1
