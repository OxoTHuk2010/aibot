"""Проверяет полноту и стабильность Swagger/OpenAPI-контракта CP1--CP5.

Тесты импортируют приложение в изолированном окружении и не обращаются к базе
данных или внешним API. Проверяется документация, а не бизнес-реализация endpoint.
"""

import asyncio
import importlib
import sys
from collections.abc import Iterator
from types import ModuleType

import pytest

UNIT_DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/aibot_test"

EXPECTED_OPERATIONS = {
    ("/api/health", "get"): ("Health", "200", "HealthResponse"),
    ("/api/sources", "post"): ("Sources", "201", "SourceResponse"),
    ("/api/sources", "get"): ("Sources", "200", "SourceResponse"),
    ("/api/sources/{source_id}", "get"): ("Sources", "200", "SourceResponse"),
    ("/api/sources/{source_id}", "patch"): ("Sources", "200", "SourceResponse"),
    ("/api/sources/{source_id}", "delete"): ("Sources", "204", None),
    ("/api/sources/{source_id}/parse", "post"): (
        "Sources",
        "200",
        "ParseSourceResponse",
    ),
    ("/api/keywords", "post"): ("Keywords", "201", "KeywordResponse"),
    ("/api/keywords", "get"): ("Keywords", "200", "KeywordResponse"),
    ("/api/keywords/{keyword_id}", "get"): ("Keywords", "200", "KeywordResponse"),
    ("/api/keywords/{keyword_id}", "patch"): ("Keywords", "200", "KeywordResponse"),
    ("/api/keywords/{keyword_id}", "delete"): ("Keywords", "204", None),
    ("/api/news", "get"): ("News", "200", "NewsItemResponse"),
    ("/api/news/{news_id}", "get"): ("News", "200", "NewsItemResponse"),
    ("/api/generate/test", "post"): ("Generation", "200", "GenerateTestResponse"),
    ("/api/generate", "post"): ("Generation", "201", "PostResponse"),
    ("/api/posts", "get"): ("Posts", "200", "PostResponse"),
    ("/api/posts/{post_id}", "get"): ("Posts", "200", "PostResponse"),
    ("/api/posts/{post_id}/publish", "post"): ("Posts", "200", "PostResponse"),
}

EXPECTED_ERROR_RESPONSES = {
    ("/api/sources", "post"): {"409", "422"},
    ("/api/sources/{source_id}", "get"): {"404", "422"},
    ("/api/sources/{source_id}", "patch"): {"404", "409", "422"},
    ("/api/sources/{source_id}", "delete"): {"404", "422"},
    ("/api/sources/{source_id}/parse", "post"): {"400", "404", "409", "422", "502"},
    ("/api/keywords", "post"): {"409", "422"},
    ("/api/keywords/{keyword_id}", "get"): {"404", "422"},
    ("/api/keywords/{keyword_id}", "patch"): {"404", "409", "422"},
    ("/api/keywords/{keyword_id}", "delete"): {"404", "422"},
    ("/api/news/{news_id}", "get"): {"404", "422"},
    ("/api/generate/test", "post"): {"422", "502", "503", "504"},
    ("/api/generate", "post"): {"404", "409", "422", "502", "503", "504"},
    ("/api/posts/{post_id}", "get"): {"404", "422"},
    ("/api/posts/{post_id}/publish", "post"): {"404", "409", "422", "502", "503"},
}


@pytest.fixture(scope="module")
def openapi_module(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ModuleType]:
    """Импортирует приложение без чтения пользовательского ``.env``."""
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.chdir(tmp_path_factory.mktemp("openapi-settings"))
    monkeypatch.setenv("DATABASE_URL", UNIT_DATABASE_URL)
    monkeypatch.setenv("APP_ENV", "test")

    for module_name in (
        "app.main",
        "app.api.generate",
        "app.api.posts",
        "app.database",
        "app.config",
    ):
        sys.modules.pop(module_name, None)

    module = importlib.import_module("app.main")
    yield module

    database = importlib.import_module("app.database")
    asyncio.run(database.dispose_engine())
    monkeypatch.undo()


def _response_schema_name(operation: dict[str, object], status_code: str) -> str | None:
    """Извлекает имя response schema для объекта или элементов массива."""
    responses = operation["responses"]
    assert isinstance(responses, dict)
    response = responses[status_code]
    assert isinstance(response, dict)
    content = response.get("content")
    if content is None:
        return None
    assert isinstance(content, dict)
    media_type = content["application/json"]
    assert isinstance(media_type, dict)
    schema = media_type["schema"]
    assert isinstance(schema, dict)
    if schema.get("type") == "array":
        schema = schema["items"]
        assert isinstance(schema, dict)
    reference = schema.get("$ref")
    assert isinstance(reference, str)
    return reference.rsplit("/", maxsplit=1)[-1]


def test_openapi_metadata_and_tags(openapi_module: ModuleType) -> None:
    """Проверяет название, описание, версию и шесть согласованных групп API."""
    document = openapi_module.app.openapi()

    assert document["info"]["title"]
    assert document["info"]["description"]
    assert document["info"]["version"] == "1.0.0"
    assert [tag["name"] for tag in document["tags"]] == [
        "Health",
        "Sources",
        "Keywords",
        "News",
        "Generation",
        "Posts",
    ]
    assert all(tag.get("description") for tag in document["tags"])


def test_openapi_contains_every_actual_operation(openapi_module: ModuleType) -> None:
    """Проверяет, что OpenAPI содержит каждый фактический прикладной маршрут."""
    document = openapi_module.app.openapi()
    actual = {
        (path, method)
        for path, path_item in document["paths"].items()
        for method in path_item
        if method in {"get", "post", "patch", "delete"}
    }

    assert actual == set(EXPECTED_OPERATIONS)


def test_operations_have_descriptions_and_response_models(openapi_module: ModuleType) -> None:
    """Проверяет tag, summary, description, success status и response model endpoint-ов."""
    document = openapi_module.app.openapi()

    for (path, method), (tag, success_status, schema_name) in EXPECTED_OPERATIONS.items():
        operation = document["paths"][path][method]
        assert operation["tags"] == [tag]
        assert operation.get("summary")
        assert operation.get("description")
        assert success_status in operation["responses"]
        assert _response_schema_name(operation, success_status) == schema_name


def test_operations_document_actual_error_statuses(openapi_module: ModuleType) -> None:
    """Проверяет явное описание основных ошибок HTTP, реализованных router-слоем."""
    document = openapi_module.app.openapi()

    for (path, method), expected_statuses in EXPECTED_ERROR_RESPONSES.items():
        responses = document["paths"][path][method]["responses"]
        assert expected_statuses <= set(responses)
        assert all(responses[status]["description"] for status in expected_statuses)


def test_important_schema_fields_have_descriptions(openapi_module: ModuleType) -> None:
    """Проверяет описания полей типов, статусов, enabled и входа генерации."""
    schemas = openapi_module.app.openapi()["components"]["schemas"]
    expected_fields = {
        "SourceCreate": {"source_type", "enabled"},
        "SourceUpdate": {"source_type", "enabled"},
        "KeywordCreate": {"type", "enabled"},
        "KeywordUpdate": {"type", "enabled"},
        "NewsItemResponse": {"status"},
        "GeneratePostRequest": {"news_ids"},
        "GenerateTestRequest": {"text"},
        "PostResponse": {"status", "news_ids"},
    }

    for schema_name, field_names in expected_fields.items():
        properties = schemas[schema_name]["properties"]
        assert all(properties[field_name].get("description") for field_name in field_names)


def test_pagination_parameters_have_descriptions(openapi_module: ModuleType) -> None:
    """Проверяет описание limit/offset во всех collection endpoint-ах."""
    document = openapi_module.app.openapi()

    for path in ("/api/sources", "/api/keywords", "/api/news", "/api/posts"):
        parameters = document["paths"][path]["get"]["parameters"]
        by_name = {parameter["name"]: parameter for parameter in parameters}
        assert by_name["limit"]["description"]
        assert by_name["offset"]["description"]

