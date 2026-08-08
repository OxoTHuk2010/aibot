"""Определяет публичные Pydantic-схемы HTTP API.

Схемы отделяют входные и выходные контракты от ORM-моделей и запрещают лишние
поля во входных данных. Описания полей используются в OpenAPI без изменения
принятых правил валидации CP1--CP5.
"""

from datetime import datetime
from typing import Literal, Self

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import KeywordType, NewsItemStatus, Post, PostStatus, SourceType


class InputSchema(BaseModel):
    """Запрещает поля за пределами опубликованного входного контракта API."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceFields(InputSchema):
    """Содержит общие поля создания и полного представления источника."""

    name: str = Field(min_length=1, max_length=200, description="Понятное имя источника.")
    source_type: SourceType = Field(
        description="Тип адаптера источника: RSS, HTML-страница или публичный Telegram-канал."
    )
    url: AnyHttpUrl = Field(max_length=500, description="HTTP(S)-адрес источника новостей.")
    enabled: bool = Field(
        default=True,
        description="Разрешён ли ручной и автоматический сбор из источника.",
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        """Удаляет внешние пробелы и отклоняет имя без значимых символов."""
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class SourceCreate(SourceFields):
    """Описывает данные для создания источника новостей."""


class SourceUpdate(InputSchema):
    """Описывает частичное изменение источника без поддержки явного null."""

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        description="Новое понятное имя источника.",
    )
    source_type: SourceType | None = Field(
        default=None,
        description="Новый тип адаптера источника.",
    )
    url: AnyHttpUrl | None = Field(
        default=None,
        max_length=500,
        description="Новый уникальный HTTP(S)-адрес источника.",
    )
    enabled: bool | None = Field(
        default=None,
        description="Включает или отключает сбор из источника.",
    )

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        """Нормализует переданное имя, сохраняя отсутствие поля при PATCH."""
        if value is None:
            return value
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value

    @model_validator(mode="after")
    def validate_patch(self) -> Self:
        """Требует хотя бы одно поле и запрещает явный null в PATCH."""
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        if any(getattr(self, field_name) is None for field_name in self.model_fields_set):
            raise ValueError("explicit null is not allowed")
        return self


class SourceResponse(BaseModel):
    """Представляет сохранённый источник вместе со служебными метками времени."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source_type: SourceType = Field(description="Тип парсера источника.")
    url: str
    enabled: bool = Field(description="Разрешён ли сбор новостей из источника.")
    last_parsed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class KeywordFields(InputSchema):
    """Содержит общие поля правила фильтрации новостей."""

    word: str = Field(
        min_length=1,
        max_length=100,
        description="Подстрока для регистронезависимого поиска в новости.",
    )
    type: KeywordType = Field(
        default=KeywordType.INCLUDE,
        description="Тип правила: включающее или исключающее; исключение имеет приоритет.",
    )
    enabled: bool = Field(default=True, description="Участвует ли правило в фильтрации.")

    @field_validator("word")
    @classmethod
    def normalize_word(cls, value: str) -> str:
        """Приводит слово к каноническому регистронезависимому виду."""
        value = value.strip().casefold()
        if not value:
            raise ValueError("word must not be blank")
        if len(value) > 100:
            raise ValueError("normalized word must not exceed 100 characters")
        return value


class KeywordCreate(KeywordFields):
    """Описывает данные для создания правила фильтрации."""


class KeywordUpdate(InputSchema):
    """Описывает частичное изменение правила без поддержки явного null."""

    word: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Новая нормализуемая подстрока правила.",
    )
    type: KeywordType | None = Field(default=None, description="Новый тип правила.")
    enabled: bool | None = Field(
        default=None,
        description="Включает или отключает правило фильтрации.",
    )

    @field_validator("word")
    @classmethod
    def normalize_word(cls, value: str | None) -> str | None:
        """Нормализует переданное слово, сохраняя отсутствие поля при PATCH."""
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
        """Требует хотя бы одно поле и запрещает явный null в PATCH."""
        if not self.model_fields_set:
            raise ValueError("at least one field must be provided")
        if any(getattr(self, field_name) is None for field_name in self.model_fields_set):
            raise ValueError("explicit null is not allowed")
        return self


class KeywordResponse(BaseModel):
    """Представляет сохранённое правило фильтрации."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    word: str
    type: KeywordType = Field(description="Тип включающего или исключающего правила.")
    enabled: bool = Field(description="Участвует ли правило в фильтрации.")
    created_at: datetime
    updated_at: datetime


class ParseSourceResponse(BaseModel):
    """Содержит итоговые счётчики одного ручного разбора источника."""

    source_id: int
    found: int
    created: int
    duplicates: int
    filtered: int
    errors: int


class NewsItemResponse(BaseModel):
    """Представляет нормализованную новость и результат её фильтрации."""
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
    status: NewsItemStatus = Field(
        description="Состояние новости: новая, отфильтрованная или ошибочная."
    )
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class GeneratePostRequest(InputSchema):
    """Задаёт новости, из которых требуется сформировать новый пост."""

    news_ids: list[int] = Field(
        min_length=1,
        max_length=10,
        description=(
            "Идентификаторы 1--10 существующих новостей со статусом new; "
            "повторяющиеся значения удаляются с сохранением порядка."
        ),
    )

    @field_validator("news_ids")
    @classmethod
    def validate_news_ids(cls, value: list[int]) -> list[int]:
        """Отклоняет неположительные ID и стабильно удаляет повторы."""
        if any(news_id <= 0 for news_id in value):
            raise ValueError("news ids must be positive integers")
        return list(dict.fromkeys(value))


class GenerateTestRequest(InputSchema):
    """Передаёт ручной текст для проверки настроенного AI-провайдера."""

    text: str = Field(
        min_length=1,
        max_length=16_000,
        description="Исходный материал для тестовой генерации без записи в PostgreSQL.",
    )

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        """Удаляет внешние пробелы и отклоняет пустой исходный материал."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("text must not be blank")
        return normalized


class GenerateTestResponse(BaseModel):
    """Возвращает тестовый текст, сформированный AI-провайдером."""

    generated_text: str = Field(description="Сформированный текст Telegram-поста.")


class HealthResponse(BaseModel):
    """Подтверждает, что HTTP-процесс способен обработать запрос."""

    status: Literal["ok"] = Field(description="Постоянный признак process liveness.")


class PostResponse(BaseModel):
    """Представляет сгенерированный пост и состояние его публикации."""

    id: int
    generated_text: str
    status: PostStatus = Field(
        description="Состояние поста: сгенерирован, опубликован или завершён ошибкой."
    )
    published_at: datetime | None
    telegram_message_id: int | None
    created_at: datetime
    updated_at: datetime
    news_ids: list[int] = Field(description="Связанные с постом идентификаторы новостей.")

    @classmethod
    def from_post(cls, post: Post) -> "PostResponse":
        """Строит API-представление из загруженного Post и его M:N-связей."""
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
