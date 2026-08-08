"""Предоставляет лёгкую проверку process liveness HTTP-приложения.

Endpoint намеренно не обращается к PostgreSQL и другим внешним сервисам.
"""

from fastapi import APIRouter

from app.schemas import HealthResponse

router = APIRouter(prefix="/health", tags=["Health"])


@router.get(
    "",
    response_model=HealthResponse,
    summary="Проверить работоспособность процесса",
    description="Возвращает process liveness без проверок PostgreSQL и внешних интеграций.",
    response_description="Процесс принимает HTTP-запросы.",
)
async def health() -> dict[str, str]:
    """Возвращает неизменяемый признак работоспособности HTTP-процесса."""
    return {"status": "ok"}
