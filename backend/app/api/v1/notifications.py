import uuid
import logging
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.models.user import User
from app.models.notification import Notification, NotificationPreference
from app.schemas.notification import NotificationResponse, NotificationPreferenceResponse, NotificationPreferenceUpdate
from app.services.notification_service import ws_manager

logger = logging.getLogger(__name__)
router = APIRouter()

import jwt
from typing import Optional
from fastapi import Query
from app.core.config import settings
from app.db.session import SessionLocal

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    client_ip = websocket.client.host if websocket.client else "unknown"
    if ws_manager.is_rate_limited(client_ip):
        logger.warning(f"WebSocket connection rejected: IP {client_ip} is rate limited.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    auth_token = token
    if not auth_token:
        auth_header = websocket.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            auth_token = auth_header.split(" ")[1]

    if not auth_token:
        logger.warning("WebSocket auth failed: Missing authentication credentials.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        payload = jwt.decode(
            auth_token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM]
        )
        user_id = payload.get("sub")
        if not user_id:
            logger.warning("WebSocket auth failed: claim payload missing subject.")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        async with SessionLocal() as db:
            stmt = select(User).filter(User.id == uuid.UUID(user_id))
            res = await db.execute(stmt)
            user = res.scalars().first()
            if not user or not user.is_active:
                logger.warning(f"WebSocket auth failed: User {user_id} is inactive or does not exist.")
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

            role = payload.get("role", "operator")
            if role not in ["operator", "admin"]:
                logger.warning(f"WebSocket auth failed: Incompatible user role '{role}' for user {user_id}.")
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return

    except jwt.ExpiredSignatureError:
        logger.warning("WebSocket auth failed: Signature has expired.")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    except jwt.PyJWTError as e:
        logger.warning(f"WebSocket auth failed: JWT decoding error: {str(e)}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    except Exception as e:
        logger.error(f"WebSocket auth unexpected exception: {str(e)}")
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "PING":
                await websocket.send_text("PONG")
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)

@router.get("", response_model=List[NotificationResponse])
async def list_notifications(
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    stmt = (
        select(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
    )
    res = await db.execute(stmt)
    return res.scalars().all()

@router.put("/{id}/read", response_model=NotificationResponse)
async def mark_notification_read(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    stmt = select(Notification).filter(Notification.id == id, Notification.user_id == current_user.id)
    res = await db.execute(stmt)
    noti = res.scalars().first()
    if not noti:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found."
        )
    noti.is_read = True
    await db.commit()
    await db.refresh(noti)
    return noti

@router.put("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    stmt = (
        update(Notification)
        .filter(Notification.user_id == current_user.id)
        .values(is_read=True)
    )
    await db.execute(stmt)
    await db.commit()
    return {"message": "All notifications marked as read."}

@router.post("/read-all", status_code=status.HTTP_200_OK)
async def mark_all_notifications_read_post(
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    return await mark_all_notifications_read(db, current_user)

@router.get("/preferences", response_model=NotificationPreferenceResponse)
async def get_preferences(
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    stmt = select(NotificationPreference).filter(NotificationPreference.user_id == current_user.id)
    res = await db.execute(stmt)
    pref = res.scalars().first()
    if not pref:
        pref = NotificationPreference(
            id=uuid.uuid4(),
            user_id=current_user.id,
            email_notifications=True,
            push_notifications=True,
            min_severity="info"
        )
        db.add(pref)
        await db.commit()
        await db.refresh(pref)
    return pref

@router.put("/preferences", response_model=NotificationPreferenceResponse)
async def update_preferences(
    payload: NotificationPreferenceUpdate,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    stmt = select(NotificationPreference).filter(NotificationPreference.user_id == current_user.id)
    res = await db.execute(stmt)
    pref = res.scalars().first()
    if not pref:
        pref = NotificationPreference(id=uuid.uuid4(), user_id=current_user.id)
        db.add(pref)
        
    if payload.email_notifications is not None:
        pref.email_notifications = payload.email_notifications
    if payload.push_notifications is not None:
        pref.push_notifications = payload.push_notifications
    if payload.min_severity is not None:
        pref.min_severity = payload.min_severity
        
    await db.commit()
    await db.refresh(pref)
    return pref

@router.post("/preferences", response_model=NotificationPreferenceResponse)
async def update_preferences_post(
    payload: NotificationPreferenceUpdate,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    return await update_preferences(payload, db, current_user)
