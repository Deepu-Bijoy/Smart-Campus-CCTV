from typing import AsyncGenerator
import uuid
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.user import User
from app.schemas.user import TokenPayload

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/auth/login"
)

import logging
logger = logging.getLogger("app.api.deps")

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        try:
            logger.debug("Dependency get_db: Session opened.")
            yield session
            await session.commit()
            logger.debug("Dependency get_db: Session committed.")
        except Exception as e:
            logger.error(f"Dependency get_db: Transaction exception: {str(e)}")
            await session.rollback()
            raise

async def get_current_user(
    db: AsyncSession = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> User:
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        token_data = TokenPayload(**payload)
    except (jwt.PyJWTError, ValidationError) as e:
        logger.warning(f"Dependency get_current_user: JWT validation failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    
    if not token_data.sub:
        logger.warning("Dependency get_current_user: Token subject missing.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
        
    try:
        result = await db.execute(select(User).filter(User.id == uuid.UUID(token_data.sub)))
        user = result.scalars().first()
    except Exception as e:
        logger.error(f"Dependency get_current_user: Database query failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database connection error",
        )
    
    if not user:
        logger.warning(f"Dependency get_current_user: User with ID {token_data.sub} not found in database.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if not user.is_active:
        logger.warning(f"Dependency get_current_user: User {user.email} is inactive.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user",
        )
    logger.debug(f"Dependency get_current_user: Validated active user {user.email}")
    return user
