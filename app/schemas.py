from datetime import datetime
from typing import Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import KeywordType, NewsItemStatus, Post, PostStatus, SourceType


class InputSchema(BaseModel):
    """Reject fields outside the public management API contract."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceFields(InputSchema):
    name: str = Field(min_length=1, max_length=200)
    source_type: SourceType
    url: AnyHttpUrl = Field(max_length=500)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class SourceCreate(SourceFields):
    pass


class SourceUpdate(InputSchema):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    source_type: SourceType | None = None
    url: AnyHttpUrl | None = Field(default=None, max_length=500)
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        if any(getattr(self, field_name) is None for field_name in self.model_fields_set):
            raise ValueError("explicit null is not allowed")
        return self


class SourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_type: SourceType
    url: str
    enabled: bool
    last_parsed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KeywordFields(InputSchema):
    word: str = Field(min_length=1, max_length=100)
    type: KeywordType = KeywordType.INCLUDE
    enabled: bool = True

    @field_validator("word")
    @classmethod
    def normalize_word(cls, value: str) -> str:
        value = value.strip().casefold()
        if not value:
            raise ValueError("word must not be blank")
        if len(value) > 100:
            raise ValueError("normalized word must not exceed 100 characters")
        return value


class KeywordCreate(KeywordFields):
    pass


class KeywordUpdate(InputSchema):
    word: str | None = Field(default=None, min_length=1, max_length=100)
    type: KeywordType | None = None
    enabled: bool | None = None

    @field_validator("word")
    @classmethod
    def normalize_word(cls, value: str | None) -> str | None:
        if value is None:
            return value
        value = value.strip().casefold()
        if not value:
            raise ValueError("word must not be blank")
        if len(value) > 100:
            raise ValueError("normalized word must not exceed 100 characters")
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        if any(getattr(self, field_name) is None for field_name in self.model_fields_set):
            raise ValueError("explicit null is not allowed")
        return self


class KeywordResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    word: str
    type: KeywordType
    enabled: bool
    created_at: datetime
    updated_at: datetime


class ParseSourceResponse(BaseModel):
    source_id: int
    found: int
    created: int
    duplicates: int
    filtered: int
    errors: int


class NewsItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_id: int
    external_id: str | None
    title: str
    url: str | None
    summary: str | None
    raw_text: str | None
    published_at: datetime | None
    content_hash: str
    status: NewsItemStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class GeneratePostRequest(InputSchema):
    news_ids: list[int] = Field(min_length=1, max_length=10)

    @field_validator("news_ids")
    @classmethod
    def validate_news_ids(cls, value: list[int]) -> list[int]:
        if any(news_id <= 0 for news_id in value):
            raise ValueError("news ids must be positive integers")
        return list(dict.fromkeys(value))


class GenerateTestRequest(InputSchema):
    text: str = Field(min_length=1, max_length=16_000)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be blank")
        return normalized


class GenerateTestResponse(BaseModel):
    generated_text: str


class PostResponse(BaseModel):
    id: int
    generated_text: str
    status: PostStatus
    published_at: datetime | None
    telegram_message_id: int | None
    created_at: datetime
    updated_at: datetime
    news_ids: list[int]

    @classmethod
    def from_post(cls, post: Post) -> "PostResponse":
        return cls(
            id=post.id,
            generated_text=post.generated_text,
            status=post.status,
            published_at=post.published_at,
            telegram_message_id=post.telegram_message_id,
            created_at=post.created_at,
            updated_at=post.updated_at,
            news_ids=[item.id for item in post.news_items],
        )
