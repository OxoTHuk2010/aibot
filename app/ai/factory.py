"""Выбирает AI backend по конфигурации приложения.

Фабрика изолирует router и Celery pipeline от конкретных клиентов OpenAI и Ollama,
не вводя контейнер зависимостей или plugin registry.
"""

from app.ai.client import AIClient, AIConfigurationError
from app.ai.generator import PostGenerator, TextGenerationClient
from app.ai.ollama import OllamaClient
from app.config import Settings


def create_generator(app_settings: Settings) -> PostGenerator:
    """Создаёт генератор с настроенным OpenAI- или Ollama-клиентом.

    Неизвестный selector приводит к ``AIConfigurationError``. Наличие credentials
    проверяет конкретный backend только при фактическом обращении.
    """
    client: TextGenerationClient
    if app_settings.ai_provider == "openai":
        api_key = (
            app_settings.openai_api_key.get_secret_value()
            if app_settings.openai_api_key is not None
            else None
        )
        client = AIClient(
            api_key=api_key,
            model=app_settings.openai_model,
            max_tokens=app_settings.openai_max_tokens,
        )
    elif app_settings.ai_provider == "ollama":
        client = OllamaClient(
            base_url=app_settings.ollama_base_url,
            model=app_settings.ollama_model,
            timeout=app_settings.ollama_timeout,
        )
    else:
        raise AIConfigurationError("Unsupported AI provider")
    return PostGenerator(client)
