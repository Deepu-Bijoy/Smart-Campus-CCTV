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
        return {
            "status": "healthy",
            "database": "connected",
            "service": "AI-Powered CCTV System Backend"
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Database connection issue: {str(e)}"
        )
