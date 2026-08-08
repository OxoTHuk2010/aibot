from app.config import Settings
from app.publisher.bot import TelegramBotPublisher
from app.publisher.telegram import (
    TelegramPublisher,
    TelegramPublisherConfigurationError,
)

Publisher = TelegramPublisher | TelegramBotPublisher


def create_publisher(app_settings: Settings) -> Publisher:
    """Create the configured CP4 publisher without depending on an HTTP router."""
    if app_settings.telegram_publisher == "telethon":
        api_hash = (
            app_settings.telegram_api_hash.get_secret_value()
            if app_settings.telegram_api_hash is not None
            else None
        )
        return TelegramPublisher(
            api_id=app_settings.telegram_api_id,
            api_hash=api_hash,
            session_name=app_settings.telegram_session_name,
            target_channel=app_settings.telegram_target_channel,
        )
    if app_settings.telegram_publisher == "bot":
        token = (
            app_settings.telegram_bot_token.get_secret_value()
            if app_settings.telegram_bot_token is not None
            else None
        )
        return TelegramBotPublisher(
            token=token,
            target_chat_id=app_settings.telegram_target_chat_id,
        )
    raise TelegramPublisherConfigurationError("Unsupported Telegram publisher")
