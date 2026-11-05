from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import text

from app.api import deps

router = APIRouter()

@router.get("", status_code=status.HTTP_200_OK)
async def health_check(
    db: AsyncSession = Depends(deps.get_db)
) -> dict:
    try:
        await db.execute(text("SELECT 1"))
        from app.tasks.cel_app import get_celery_worker_status
        w_status = get_celery_worker_status(timeout=0.2)
        return {
            "status": "healthy",
            "database": "connected",
            "celery_worker": "online" if w_status.get("online") else "offline",
            "service": "AI-Powered CCTV System Backend"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection issue: {str(e)}"
        )

@router.get("/worker", status_code=status.HTTP_200_OK)
async def worker_health_check() -> dict:
    """
    Operator endpoint to verify whether background Celery workers and queues are active.
    """
    from app.tasks.cel_app import get_celery_worker_status
    w_info = get_celery_worker_status(timeout=0.5)
    return {
        "status": "online" if w_info.get("online") else "offline",
        "eager_mode": w_info.get("eager", False),
        "workers": w_info.get("workers", []),
        "active_queues": w_info.get("active_queues", []),
        "error": w_info.get("error")
    }
