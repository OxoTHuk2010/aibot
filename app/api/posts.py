from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_session
from app.models import PostStatus
from app.publisher.factory import Publisher, create_publisher
from app.publisher.telegram import (
    TelegramPublisherConfigurationError,
    TelegramPublishError,
)
from app.schemas import PostResponse
from app.services.post_service import (
    PostAlreadyPublishedError,
    PostNotFoundError,
    PostNotPublishableError,
    get_post,
    list_posts,
    publish_post,
)

router = APIRouter(prefix="/posts", tags=["Posts"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def get_publisher() -> Publisher:
    return create_publisher(settings)


PublisherDependency = Annotated[Publisher, Depends(get_publisher)]


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")


@router.get("", response_model=list[PostResponse])
async def list_all(
    session: SessionDependency,
    post_status: Annotated[PostStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PostResponse]:
    posts = await list_posts(
        session,
        status=post_status,
        limit=limit,
        offset=offset,
    )
    return [PostResponse.from_post(post) for post in posts]


@router.get("/{post_id}", response_model=PostResponse)
async def get_one(post_id: int, session: SessionDependency) -> PostResponse:
    try:
        post = await get_post(session, post_id)
    except PostNotFoundError as error:
        raise _not_found() from error
    return PostResponse.from_post(post)


@router.post("/{post_id}/publish", response_model=PostResponse)
async def publish(
    post_id: int,
    session: SessionDependency,
    publisher: PublisherDependency,
) -> PostResponse:
    try:
        post = await publish_post(session, post_id, publisher)
    except PostNotFoundError as error:
        raise _not_found() from error
    except PostAlreadyPublishedError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Post is already published",
        ) from error
    except PostNotPublishableError as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Post is not publishable",
        ) from error
    except TelegramPublisherConfigurationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Telegram publication is not configured",
        ) from error
    except TelegramPublishError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Telegram publication failed",
        ) from error
    return PostResponse.from_post(post)
