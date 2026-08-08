"""Инкапсулирует обращение к локальному Ollama Chat API.

Адаптер реализует общий контракт AI-клиента через httpx и преобразует сетевые или
структурные ошибки ответа в типизированные прикладные исключения.
"""

from typing import Any

import httpx

from app.ai.client import AIInvalidResponseError, AIProviderError, AITimeoutError


class OllamaClient:
    """Адаптирует Ollama Chat API к внутреннему контракту генерации."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        timeout: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Сохраняет адрес, модель, timeout и необязательный HTTP-клиент для тестов."""
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.client = client

    async def generate_text(self, *, instructions: str, source_content: str) -> str:
        """Запрашивает у Ollama текст с разделёнными system и user сообщениями.

        Метод выполняет внешний HTTP-запрос. Недоступная модель, сетевой timeout и
        некорректный JSON преобразуются в безопасные внутренние ошибки.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": source_content},
            ],
            "stream": False,
        }
        try:
            if self.client is not None:
                response = await self.client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    timeout=self.timeout,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.base_url}/api/chat",
                        json=payload,
                        timeout=self.timeout,
                    )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise AITimeoutError("Ollama timed out or could not connect") from error

        if response.status_code == 404:
            raise AIProviderError("Configured Ollama model is unavailable")
        if response.is_error:
            raise AIProviderError("Ollama provider request failed")

        try:
            body = response.json()
            message = body.get("message") if isinstance(body, dict) else None
            generated_text = message.get("content") if isinstance(message, dict) else None
        except ValueError as error:
            raise AIInvalidResponseError("Ollama returned malformed JSON") from error

        if not isinstance(generated_text, str) or not generated_text.strip():
            raise AIInvalidResponseError("Ollama returned an empty or malformed response")
        return generated_text.strip()
