"""Создаёт Celery application, расписание Beat и зарегистрированную задачу pipeline.

RabbitMQ используется только как broker, result backend отсутствует. Синхронная
задача создаёт отдельный asyncio event loop для одного запуска pipeline.
"""

import asyncio

from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]

from app.config import settings
from app.tasks.pipeline import run_pipeline_async


class CeleryConfigurationError(RuntimeError):
    """Сообщает, что worker или Beat запущен без обязательного RabbitMQ URL."""


def create_celery_app() -> Celery:
    """Создаёт однозадачное Celery application поверх RabbitMQ.

    Конфигурация использует JSON, UTC, prefetch 1 и стандартный Beat с запуском
    каждые 30 минут. Отсутствующий broker приводит к явной ошибке запуска.
    """
    if not settings.rabbitmq_url:
        raise CeleryConfigurationError("RABBITMQ_URL is required for Celery worker and beat")
    application = Celery("aibot", broker=settings.rabbitmq_url)
    application.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        result_backend=None,
        task_ignore_result=True,
        timezone="UTC",
        enable_utc=True,
        task_acks_late=False,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        beat_schedule={
            "run-pipeline-every-30-minutes": {
                "task": "app.tasks.run_pipeline",
                "schedule": crontab(minute="*/30"),
            }
        },
    )
    return application


celery_app = create_celery_app()


@celery_app.task(name="app.tasks.run_pipeline", ignore_result=True)
def run_pipeline() -> dict[str, int]:
    """Запускает один async pipeline из синхронной доставки Celery.

    Возвращаемые счётчики JSON-сериализуемы, хотя result backend намеренно отключён.
    Ошибка инфраструктуры не поглощается и помечает delivery неуспешной.
    """
    return asyncio.run(run_pipeline_async())
