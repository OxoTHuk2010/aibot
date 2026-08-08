from typing import Annotated, NoReturn

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.client import (
    AIAuthenticationError,
    AIConfigurationError,
    AIInvalidResponseError,
    AIProviderError,
    AIRateLimitError,
    AITimeoutError,
)
from app.ai.factory import create_generator
from app.ai.generator import PostGenerator
from app.config import settings
from app.database import get_session
from app.schemas import (
    GeneratePostRequest,
    GenerateTestRequest,
    GenerateTestResponse,
    PostResponse,
)
from app.services.post_service import (
    InvalidNewsItemStateError,
    NewsItemsNotFoundError,
    generate_post,
)

router = APIRouter(prefix="/generate", tags=["Generation"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_generator() -> PostGenerator:
    return create_generator(settings)


GeneratorDependency = Annotated[PostGenerator, Depends(get_generator)]


def _raise_ai_http(error: Exception) -> NoReturn:
    if isinstance(error, AIConfigurationError):
        detail = "AI generation is not configured"
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(error, AIAuthenticationError):
        detail = "AI provider authentication failed"
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(error, AIRateLimitError):
        detail = "AI provider rate limit reached"
        status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(error, AITimeoutError):
        detail = "AI provider timed out"
        status_code = status.HTTP_504_GATEWAY_TIMEOUT
    else:
        detail = "AI provider failed to generate content"
        status_code = status.HTTP_502_BAD_GATEWAY
    raise HTTPException(status_code=status_code, detail=detail) from error


@router.post("/test", response_model=GenerateTestResponse)
async def test_generation(
    data: GenerateTestRequest,
    generator: GeneratorDependency,
) -> GenerateTestResponse:
    try:
        generated_text = await generator.generate_from_text(data.text)
    except (
        AIConfigurationError,
        AIAuthenticationError,
        AIRateLimitError,
        AITimeoutError,
        AIInvalidResponseError,
        AIProviderError,
    ) as error:
        _raise_ai_http(error)
    return GenerateTestResponse(generated_text=generated_text)


@router.post("", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def generate(
    data: GeneratePostRequest,
    session: SessionDependency,
    generator: GeneratorDependency,
) -> PostResponse:
    try:
        post = await generate_post(session, data.news_ids, generator)
    except NewsItemsNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more news items were not found",
        ) from error
    except InvalidNewsItemStateError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only news items with status=new can be generated",
        ) from error
    except (
        AIConfigurationError,
        AIAuthenticationError,
        AIRateLimitError,
        AITimeoutError,
        AIInvalidResponseError,
        AIProviderError,
    ) as error:
        _raise_ai_http(error)
    return PostResponse.from_post(post)
