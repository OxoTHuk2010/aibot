from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or ``.env``."""

    database_url: str = Field(description="Async PostgreSQL connection URL")

    # Optional infrastructure integrations used by later project stages.
    rabbitmq_url: str | None = Field(default=None, description="RabbitMQ broker URL")
    redis_url: str | None = Field(default=None, description="Redis connection URL")

    # Optional Telegram integration.
    telegram_api_id: int | None = Field(default=None, description="Telegram application ID")
    telegram_api_hash: SecretStr | None = Field(
        default=None,
        description="Telegram application hash",
    )
    telegram_session_name: str = Field(default="aibot", description="Telegram session name")
    telegram_target_channel: str | None = Field(
        default=None,
        description="Telegram channel used for publishing",
    )

    # Optional OpenAI integration.
    openai_api_key: SecretStr | None = Field(default=None, description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o-mini", description="OpenAI model name")
    openai_max_tokens: int = Field(
        default=300,
        ge=50,
        le=4000,
        description="Maximum number of output tokens",
    )

    # News collection settings.
    parse_interval: int = Field(
        default=30,
        ge=1,
        description="Interval between collection runs in minutes",
    )
    max_news_per_source: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum news items collected from one source per run",
    )

    # Application settings.
    app_env: Literal["dev", "test", "prod"] = Field(
        default="dev",
        description="Application environment",
    )
    log_level: str = Field(default="INFO")
    app_name: str = Field(default="aibot")

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use the postgresql+asyncpg:// scheme")
        return value

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def empty_optional_integer_is_none(cls, value: object) -> object:
        """Allow Compose to pass an unset optional numeric integration value."""
        return None if value == "" else value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
