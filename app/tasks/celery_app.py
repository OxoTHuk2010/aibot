import asyncio

from celery import Celery  # type: ignore[import-untyped]
from celery.schedules import crontab  # type: ignore[import-untyped]

from app.config import settings
from app.tasks.pipeline import run_pipeline_async


class CeleryConfigurationError(RuntimeError):
    """The worker cannot start without its optional application broker setting."""


def create_celery_app() -> Celery:
    """Build the single-queue Celery application backed only by RabbitMQ."""
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
    """Bridge one synchronous Celery delivery to one async pipeline event loop."""
    return asyncio.run(run_pipeline_async())
