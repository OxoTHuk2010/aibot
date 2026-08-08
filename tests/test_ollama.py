import json

import httpx
import pytest

from app.ai.client import AIInvalidResponseError, AIProviderError, AITimeoutError
from app.ai.ollama import OllamaClient


def make_client(handler: httpx.AsyncBaseTransport) -> tuple[OllamaClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(transport=handler)
    return (
        OllamaClient(
            base_url="http://ollama.test:11434/",
            model="gemma4:e4b",
            timeout=12.5,
            client=http_client,
        ),
        http_client,
    )


@pytest.mark.asyncio
async def test_ollama_chat_request_and_successful_response() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url == "http://ollama.test:11434/api/chat"
        assert body == {
            "model": "gemma4:e4b",
            "messages": [
                {"role": "system", "content": "system rules"},
                {"role": "user", "content": "source facts"},
            ],
            "stream": False,
        }
        return httpx.Response(200, json={"message": {"content": "  Generated post  "}})

    client, http_client = make_client(httpx.MockTransport(handler))
    async with http_client:
        result = await client.generate_text(
            instructions="system rules",
            source_content="source facts",
        )
    assert result == "Generated post"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"message": {"content": ""}},
        {"message": {}},
        {"unexpected": "shape"},
    ],
)
async def test_ollama_rejects_empty_or_malformed_response(body: object) -> None:
    client, http_client = make_client(
        httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    )
    async with http_client:
        with pytest.raises(AIInvalidResponseError):
            await client.generate_text(instructions="rules", source_content="facts")


@pytest.mark.asyncio
async def test_ollama_rejects_malformed_json() -> None:
    client, http_client = make_client(
        httpx.MockTransport(lambda _: httpx.Response(200, content=b"not-json"))
    )
    async with http_client:
        with pytest.raises(AIInvalidResponseError):
            await client.generate_text(instructions="rules", source_content="facts")


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 503])
async def test_ollama_maps_unavailable_service(status_code: int) -> None:
    client, http_client = make_client(
        httpx.MockTransport(lambda _: httpx.Response(status_code, json={"error": "down"}))
    )
    async with http_client:
        with pytest.raises(AIProviderError, match="provider request failed"):
            await client.generate_text(instructions="rules", source_content="facts")


@pytest.mark.asyncio
async def test_ollama_maps_model_unavailable() -> None:
    client, http_client = make_client(
        httpx.MockTransport(lambda _: httpx.Response(404, json={"error": "model missing"}))
    )
    async with http_client:
        with pytest.raises(AIProviderError, match="model is unavailable"):
            await client.generate_text(instructions="rules", source_content="facts")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "provider_error",
    [
        httpx.ConnectError("connection refused"),
        httpx.ReadTimeout("request timed out"),
    ],
)
async def test_ollama_maps_connection_and_timeout(provider_error: Exception) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise provider_error

    client, http_client = make_client(httpx.MockTransport(handler))
    async with http_client:
        with pytest.raises(AITimeoutError):
            await client.generate_text(instructions="rules", source_content="facts")
