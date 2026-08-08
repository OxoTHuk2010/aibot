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
    """Base error exposed by the OpenAI integration."""


class AIConfigurationError(AIError):
    """Required provider configuration is absent."""


class AIAuthenticationError(AIError):
    """The provider rejected the configured credentials."""


class AIRateLimitError(AIError):
    """The provider rate limit prevented generation."""


class AITimeoutError(AIError):
    """The provider could not be reached within the request timeout."""


class AIInvalidResponseError(AIError):
    """The provider returned no usable generated text."""


class AIProviderError(AIError):
    """The provider failed for another reason."""


class AIClient:
    """Small adapter around the OpenAI Responses API."""

    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        max_tokens: int,
        timeout: float = 30.0,
        provider: Any | None = None,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.provider = provider

    async def generate_text(self, *, instructions: str, source_content: str) -> str:
        """Generate text while keeping instructions separate from source data."""
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
