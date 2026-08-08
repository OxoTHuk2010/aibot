"""Инкапсулирует обращение к OpenAI Responses API и его ошибки.

Адаптер отделяет SDK от генератора и преобразует provider-исключения в стабильные
прикладные типы без раскрытия ключа или содержимого внешнего ответа.
"""

from typing import Any

from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    RateLimitError,
)


class AIError(Exception):
    """Служит базовым типом ошибок интеграций AI-генерации."""


class AIConfigurationError(AIError):
    """Сообщает об отсутствии обязательной настройки AI-провайдера."""


class AIAuthenticationError(AIError):
    """Сообщает, что AI-провайдер отклонил credentials."""


class AIRateLimitError(AIError):
    """Сообщает, что ограничение частоты провайдера остановило генерацию."""


class AITimeoutError(AIError):
    """Сообщает, что AI-провайдер не ответил за установленное время."""


class AIInvalidResponseError(AIError):
    """Сообщает, что AI-провайдер не вернул пригодный текст."""


class AIProviderError(AIError):
    """Сообщает о прочей безопасно отображаемой ошибке AI-провайдера."""


class AIClient:
    """Адаптирует OpenAI Responses API к внутреннему контракту генератора."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        max_tokens: int,
        timeout: float = 30.0,
        provider: Any | None = None,
    ) -> None:
        """Сохраняет модель, лимиты и необязательный fake provider для тестов."""
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.provider = provider

    async def generate_text(self, *, instructions: str, source_content: str) -> str:
        """Генерирует текст, передавая инструкции отдельно от исходных данных.

        Метод выполняет внешний запрос и преобразует ожидаемые ошибки SDK в
        внутренние типы. Пустой ответ считается ``AIInvalidResponseError``.
        """
        if not self.api_key and self.provider is None:
            raise AIConfigurationError("OpenAI API key is not configured")

        provider = self.provider or AsyncOpenAI(
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=1,
        )
        try:
            response = await provider.responses.create(
                model=self.model,
                instructions=instructions,
                input=source_content,
                max_output_tokens=self.max_tokens,
            )
        except AuthenticationError as error:
            raise AIAuthenticationError("OpenAI authentication failed") from error
        except RateLimitError as error:
            raise AIRateLimitError("OpenAI rate limit reached") from error
        except (APITimeoutError, APIConnectionError) as error:
            raise AITimeoutError("OpenAI request timed out or could not connect") from error
        except APIError as error:
            raise AIProviderError("OpenAI provider request failed") from error

        generated_text = str(getattr(response, "output_text", "") or "").strip()
        if not generated_text:
            raise AIInvalidResponseError("OpenAI returned an empty response")
        return generated_text
