from typing import Any

import httpx

from app.publisher.telegram import (
    TelegramPublisherConfigurationError,
    TelegramPublishError,
)

MAX_TELEGRAM_TEXT_LENGTH = 4096


class TelegramBotPublisher:
    """Publish one plain-text message through the Telegram Bot API."""

    def __init__(
        self,
        *,
        token: str | None,
        target_chat_id: str | None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.token = token
        self.target_chat_id = target_chat_id
        self.client = client
        self.timeout = timeout

    async def publish(self, text: str) -> int:
        if not self.token or not self.target_chat_id:
            raise TelegramPublisherConfigurationError(
                "Telegram Bot API publication is not configured"
            )
        normalized_text = text.strip()
        if not normalized_text:
            raise TelegramPublishError("Telegram post text is empty")
        if len(normalized_text) > MAX_TELEGRAM_TEXT_LENGTH:
            raise TelegramPublishError("Telegram post text exceeds the Bot API limit")

        request: dict[str, Any] = {
            "chat_id": self.target_chat_id,
            "text": normalized_text,
        }
        endpoint = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            if self.client is not None:
                response = await self.client.post(
                    endpoint,
                    json=request,
                    timeout=self.timeout,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        endpoint,
                        json=request,
                        timeout=self.timeout,
                    )
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            raise TelegramPublishError("Telegram Bot API request failed") from error

        try:
            body = response.json()
        except ValueError as error:
            raise TelegramPublishError("Telegram Bot API returned malformed JSON") from error
        result = body.get("result") if isinstance(body, dict) else None
        message_id = result.get("message_id") if isinstance(result, dict) else None
        if response.is_error or not isinstance(body, dict) or body.get("ok") is not True:
            raise TelegramPublishError("Telegram Bot API rejected the message")
        if not isinstance(message_id, int):
            raise TelegramPublishError("Telegram Bot API returned no message identifier")
        return message_id
