from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, object]:
    """Liveness plus a readiness hint.

    `database_configured` is false until a Supabase project exists, which lets
    the skeleton run and be smoke-tested before Phase 0 finishes.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "environment": settings.environment,
        "database_configured": settings.configured,
    }
