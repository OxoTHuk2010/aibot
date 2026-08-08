import importlib
from collections.abc import Callable
from typing import Any


class TelegramPublisherError(Exception):
    """Base error exposed by Telegram publication."""


class TelegramPublisherConfigurationError(TelegramPublisherError):
    """Required Telegram publication configuration is absent or invalid."""


class TelegramPublishError(TelegramPublisherError):
    """Telegram failed to accept the outgoing post."""


class TelegramPublisher:
    """Send one plain-text post to the configured Telegram channel."""

    def __init__(
        self,
        *,
        api_id: int | None,
        api_hash: str | None,
        session_name: str,
        target_channel: str | None,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.session_name = session_name
        self.target_channel = target_channel
        self.client_factory = client_factory

    async def publish(self, text: str) -> int:
        """Perform the external, state-changing Telegram send operation."""
        if self.api_id is None or not self.api_hash or not self.target_channel:
            raise TelegramPublisherConfigurationError(
                "Telegram publication is not configured"
            )
        normalized_text = text.strip()
        if not normalized_text:
            raise TelegramPublishError("Telegram post text is empty")

        factory = self.client_factory or importlib.import_module("telethon").TelegramClient
        client = factory(self.session_name, self.api_id, self.api_hash)
        connected = False
        try:
            await client.connect()
            connected = True
            if not await client.is_user_authorized():
                raise TelegramPublisherConfigurationError(
                    "Telegram session is not authorized"
                )
            # Safety boundary: this call creates a real external Telegram message.
            message = await client.send_message(
                self.target_channel,
                normalized_text,
                parse_mode=None,
            )
            message_id = getattr(message, "id", None)
            if not isinstance(message_id, int):
                raise TelegramPublishError("Telegram returned no message identifier")
            return message_id
        except TelegramPublisherConfigurationError:
            raise
        except TelegramPublishError:
            raise
        except Exception as error:
            raise TelegramPublishError("Telegram publication failed") from error
        finally:
            if connected:
                await client.disconnect()
