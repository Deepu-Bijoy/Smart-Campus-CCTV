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

from starlette.websockets import WebSocketState

WS_4401_UNAUTHORIZED = 4401
WS_4403_FORBIDDEN = 4403
WS_4429_RATE_LIMITED = 4429

async def _safe_close(
    websocket: WebSocket,
    code: int = status.WS_1008_POLICY_VIOLATION,
    reason: Optional[str] = None
):
    try:
        app_state = getattr(websocket, "application_state", None)
        client_state = getattr(websocket, "client_state", None)
        # If still in CONNECTING state, accept first so that the WebSocket close frame
        # with our specific RFC private close code (e.g., 4401, 4429) is transmitted
        # to the client rather than an HTTP 403 upgrade error.
        if app_state == WebSocketState.CONNECTING:
            await websocket.accept()
            app_state = getattr(websocket, "application_state", None)
        if app_state != WebSocketState.DISCONNECTED and client_state != WebSocketState.DISCONNECTED:
            await websocket.close(code=code, reason=reason)
    except Exception:
        pass

@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    client_ip = websocket.client.host if websocket.client else "unknown"
    if ws_manager.is_rate_limited(client_ip):
        logger.warning(f"WebSocket connection rejected: IP {client_ip} is rate limited.")
        await _safe_close(websocket, code=WS_4429_RATE_LIMITED, reason="Rate limited")
        return

    auth_token = token
    if not auth_token:
        auth_header = websocket.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            auth_token = auth_header.split(" ")[1]

    if not auth_token:
        logger.warning("WebSocket auth failed: Missing authentication credentials.")
        await _safe_close(websocket, code=WS_4401_UNAUTHORIZED, reason="Missing credentials")
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
            await _safe_close(websocket, code=WS_4401_UNAUTHORIZED, reason="Invalid token subject")
            return

        async with SessionLocal() as db:
            stmt = select(User).filter(User.id == uuid.UUID(user_id))
            res = await db.execute(stmt)
            user = res.scalars().first()
            if not user or not user.is_active:
                logger.warning(f"WebSocket auth failed: User {user_id} is inactive or does not exist.")
                await _safe_close(websocket, code=WS_4401_UNAUTHORIZED, reason="User inactive or not found")
                return

            role = payload.get("role", "operator")
            if role not in ["operator", "admin"]:
                logger.warning(f"WebSocket auth failed: Incompatible user role '{role}' for user {user_id}.")
                await _safe_close(websocket, code=WS_4403_FORBIDDEN, reason="Insufficient permissions")
                return

    except jwt.ExpiredSignatureError:
        logger.warning("WebSocket auth failed: Signature has expired.")
        await _safe_close(websocket, code=WS_4401_UNAUTHORIZED, reason="Token expired")
        return
    except jwt.PyJWTError as e:
        logger.warning(f"WebSocket auth failed: JWT decoding error: {str(e)}")
        await _safe_close(websocket, code=WS_4401_UNAUTHORIZED, reason="Invalid token")
        return
    except Exception as e:
        logger.error(f"WebSocket auth unexpected exception: {str(e)}")
        await _safe_close(websocket, code=status.WS_1008_POLICY_VIOLATION, reason="Auth error")
        return

    connected = False
    try:
        connected = await ws_manager.connect(websocket, user_id=str(user_id))
        if not connected:
            return

        # Record successful connection and clear rate limit strikes for this client
        ws_manager.record_successful_connection(client_ip, user_id=str(user_id))

        while True:
            data = await websocket.receive_text()
            if data == "PING":
                await websocket.send_text("PONG")
    except (WebSocketDisconnect, RuntimeError, Exception) as exc:
        logger.debug(f"WebSocket session ended: {exc}")
    finally:
        if connected:
            ws_manager.disconnect(websocket, user_id=str(user_id))

@router.get("", response_model=List[NotificationResponse])
async def list_notifications(
    unread_only: bool = Query(False, description="Filter for unread notifications only"),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    stmt = select(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        stmt = stmt.filter(Notification.is_read == False)
    stmt = stmt.order_by(Notification.created_at.desc())
    res = await db.execute(stmt)
    return res.scalars().all()

@router.delete("/{id}", status_code=status.HTTP_200_OK)
async def delete_notification(
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
    await db.delete(noti)
    await db.commit()
    return {"message": "Notification deleted successfully."}

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
