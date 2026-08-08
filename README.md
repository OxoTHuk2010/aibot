# aibot

Учебный FastAPI-сервис, который собирает новости из RSS/HTML/Telegram, фильтрует их,
генерирует Telegram-посты через OpenAI или локальный Ollama и публикует через Telethon
или Telegram Bot API. Celery связывает готовые этапы в автоматический pipeline.

## Architecture

- FastAPI предоставляет management, ingestion, generation, publication и health API.
- PostgreSQL хранит Source, Keyword, NewsItem, Post и M:N-связи.
- Celery worker использует RabbitMQ как единственный broker; result backend отсутствует.
- Celery Beat отправляет `app.tasks.run_pipeline` каждые 30 минут (`*/30`).
- Pipeline переиспользует существующие ingestion, generation и publication services.
- Redis остаётся подготовленной инфраструктурой и pipeline не используется.

## Requirements

- Python 3.12 или 3.13 для локального запуска;
- PostgreSQL и RabbitMQ либо Docker Compose;
- Redis запускается Compose, но не обязателен для приложения/pipeline;
- для demo: локальный Ollama с установленной моделью и настроенный Telegram backend.

## Configuration

Полный документированный пример находится в `.env.example`. Для приложения обязателен
только async `DATABASE_URL`. Worker/Beat дополнительно требуют `RABBITMQ_URL`.

Ключевые настройки pipeline:

- `AUTO_PUBLISH=false` — безопасный default: создавать Post, но не отправлять Telegram;
- `PIPELINE_MAX_POSTS_PER_RUN=2` — максимум Post за один запуск;
- `PIPELINE_NEWS_PER_POST=5` — максимум NewsItem в одном Post;
- `AI_PROVIDER=openai|ollama` и `TELEGRAM_PUBLISHER=telethon|bot` выбирают CP4 backend.

## Deployment

```powershell
docker compose build
docker compose up -d
docker compose ps
```

Ожидаемая последовательность: PostgreSQL/RabbitMQ healthy, migrate exit 0, затем app,
worker и beat running. FastAPI не зависит от состояния worker/Beat/RabbitMQ.

Не ожидая Beat, pipeline можно отправить вручную:

```powershell
docker compose exec worker celery -A app.tasks.celery_app:celery_app call app.tasks.run_pipeline
```

## Safety model

`AUTO_PUBLISH=true` выполняет реальную внешнюю отправку Telegram. Включайте его только с
тестовым target или после проверки конфигурации. Один Compose worker работает с
`--concurrency=1`; distributed lock и distributed exactly-once отсутствуют. RabbitMQ delivery
acknowledges до выполнения задачи (`task_acks_late=false`), чтобы crash не создавал автоматический
повтор публикации; следующий запуск Beat повторит ещё не выполненную работу там, где состояние БД
это допускает.

Частичная ошибка Source/AI/Telegram записывается в summary и не отменяет успешные независимые
этапы. Ошибка PostgreSQL завершает task с failure. Секреты, полный prompt, NewsItem и Post в логи
не выводятся.

## Testing

Unit-тестам не нужны RabbitMQ, Ollama, Telegram или Internet. Integration tests используют
настоящий PostgreSQL через `DATABASE_URL` и требуют `APP_ENV=test`.

```powershell
python -m pytest
python -m ruff check .
python -m mypy app tests
python -m alembic check
```

## Troubleshooting

- Worker/Beat завершается при старте: проверьте `RABBITMQ_URL` и RabbitMQ health.
- App работает, worker нет: это допустимая изоляция; `/api/health` проверяет только liveness.
- Ollama из Docker недоступен: на Docker Desktop используйте
  `OLLAMA_BASE_URL=http://host.docker.internal:11434`.
- Post остаётся `generated`: проверьте `AUTO_PUBLISH`, publisher credentials и сетевой доступ к
  Telegram. CP5 не добавляет retry queue для неудачной публикации.
