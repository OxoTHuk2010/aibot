"""Загружает и проверяет конфигурацию приложения из environment или ``.env``.

DATABASE_URL остаётся единственной обязательной настройкой базового приложения.
Параметры внешних интеграций необязательны до момента вызова соответствующего компонента.
"""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Хранит проверенные настройки процесса приложения.

    Неизвестные Compose-переменные игнорируются, а секреты сохраняются в ``SecretStr``.
    PostgreSQL URL обязан явно выбирать асинхронный драйвер asyncpg.
    """

    database_url: str = Field(description="Асинхронный URL подключения к PostgreSQL.")

    # Необязательные инфраструктурные интеграции следующих этапов.
    rabbitmq_url: str | None = Field(default=None, description="URL брокера RabbitMQ.")
    redis_url: str | None = Field(default=None, description="URL подключения к Redis.")

    # Необязательная интеграция с Telegram.
    telegram_api_id: int | None = Field(default=None, description="ID приложения Telegram.")
    telegram_api_hash: SecretStr | None = Field(
        default=None,
        description="Секретный hash приложения Telegram.",
    )
    telegram_session_name: str = Field(default="aibot", description="Имя сессии Telegram.")
    telegram_target_channel: str | None = Field(
        default=None,
        description="Канал Telegram для публикации через Telethon.",
    )
    telegram_publisher: Literal["telethon", "bot"] = Field(
        default="telethon",
        description="Backend публикации в Telegram.",
    )
    telegram_bot_token: SecretStr | None = Field(
        default=None,
        description="Секретный токен Telegram Bot API.",
    )
    telegram_target_chat_id: str | None = Field(
        default=None,
        description="Целевой чат или приватный канал Telegram Bot API.",
    )

    # Необязательная интеграция с AI-провайдерами.
    ai_provider: Literal["openai", "ollama"] = Field(
        default="openai",
        description="Backend генерации текста.",
    )
    openai_api_key: SecretStr | None = Field(default=None, description="Секретный ключ OpenAI API.")
    openai_model: str = Field(default="gpt-4o-mini", description="Имя модели OpenAI.")
    openai_max_tokens: int = Field(
        default=300,
        ge=50,
        le=4000,
        description="Максимальное число токенов в ответе OpenAI.",
    )

    # Необязательная локальная интеграция с Ollama.
    ollama_base_url: str = Field(
        default="http://localhost:11434",
        description="Базовый URL HTTP API Ollama.",
    )
    ollama_model: str = Field(default="gemma4:e4b", description="Имя модели Ollama.")
    ollama_timeout: float = Field(
        default=120.0,
        gt=0,
        le=600,
        description="Тайм-аут запроса Ollama в секундах.",
    )

    # Настройки сбора новостей.
    parse_interval: int = Field(
        default=30,
        ge=1,
        description="Интервал между запусками сбора в минутах.",
    )
    max_news_per_source: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Максимум новостей из одного источника за запуск.",
    )

    # Настройки автоматического pipeline.
    auto_publish: bool = Field(
        default=False,
        description="Публиковать ли автоматически успешно сгенерированные посты.",
    )
    pipeline_max_posts_per_run: int = Field(
        default=2,
        ge=1,
        le=10,
        description="Максимум постов за один запуск pipeline.",
    )
    pipeline_news_per_post: int = Field(
        default=5,
        ge=1,
        le=10,
        description="Максимум новостей в одном сгенерированном посте.",
    )

    # Общие настройки приложения.
    app_env: Literal["dev", "test", "prod"] = Field(
        default="dev",
        description="Окружение приложения: dev, test или prod.",
    )
    log_level: str = Field(default="INFO")
    app_name: str = Field(default="aibot")

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        """Требует URL PostgreSQL с асинхронным драйвером asyncpg."""
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// scheme")
        return value

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def empty_optional_integer_is_none(cls, value: object) -> object:
        """Преобразует пустое Compose-значение необязательного числа в ``None``."""
        return None if value == "" else value

    @field_validator("telegram_bot_token", "telegram_target_chat_id", mode="before")
    @classmethod
    def empty_optional_value_is_none(cls, value: object) -> object:
        """Преобразует пустые Compose-значения Bot API в ``None``."""
        return None if value == "" else value

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_base_url(cls, value: str) -> str:
        """Проверяет HTTP(S)-адрес Ollama и удаляет завершающий слеш."""
        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("OLLAMA_BASE_URL must use the http:// or https:// scheme")
        return normalized

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Один раз загружает настройки процесса и возвращает кешированный объект."""
    return Settings()


settings = get_settings()
