from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from functools import lru_cache

class Settings(BaseSettings):
    """
    Конфигурация приложения
    """
    database_url: str = Field(..., description='postgresql+asyncpg://user:password@host_db')
    rabbitmq_url: str = Field(default='amqp://guest@rabbitmq:5672', description="URL брокера RabbitMQ")
    redis_url: str = Field(default='redis://redis:6379/0', description='URL для redis')

    #tg
    telegram_api_id: int = Field(..., description='App telegram api_id')
    telegram_api_hash: str = Field(..., description='App telegram api_hash')
    telegram_session_name: str = Field(default='aibot', description='Имя файла сессии')
    telegram_target_channel: str = Field(..., description='Канал для публикации постов')

    #openai
    openai_api_key: str = Field(..., description='API key OpenAI')
    openai_model: str = Field(default='gpt-4o-mini', description='используемая модель, default=gpt-4o-mini')
    openai_max_tokens: int = Field(default=300, description='Максимальное число токенов для запроса')

    #parser
    parse_interval: int = Field(default=30, description='интервал между запуском парсера в минутах')
    max_news_per_source: int = Field(default=10, description='максимальное количество новостей за запуск парсера')

    #App
    app_env: str = Field(default='dev', description='dev / prod enviroment')
    log_level: str = Field(default='INFO')

    @field_validator('app_env')
    @classmethod
    def validate_env(cls, v:str) -> str:
        allowed = {'dev', 'prod'}
        if v not in allowed:
            raise ValueError(f'app_env может быть только {allowed}')
        return v
    
    model_config = SettingsConfigDict(
        env_file='.env',
        env_file_encoding='utf-8',
        case_sensitive=False
    )

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings = get_settings()