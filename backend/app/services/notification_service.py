import uuid
import logging
import time
from datetime import datetime, timezone
from typing import List, Dict, Optional, Any
from fastapi import WebSocket
from starlette.websockets import WebSocketState, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import Notification

logger = logging.getLogger(__name__)

class WebSocketConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.user_connections: Dict[str, List[WebSocket]] = {}
        self.reconnect_attempts: Dict[str, List[float]] = {}

    def is_rate_limited(self, ip_address: str) -> bool:
        now = time.time()
        attempts = self.reconnect_attempts.get(ip_address, [])
        attempts = [t for t in attempts if now - t < 10.0]
        self.reconnect_attempts[ip_address] = attempts

        if len(attempts) >= 10:
            return True
            
        self.reconnect_attempts[ip_address].append(now)
        return False

    async def connect(self, websocket: WebSocket, user_id: Optional[str] = None) -> bool:
        """
        Accept connection safely, ensuring accept is called at most once
        and only when the connection is in CONNECTING state.
        Associates the websocket with user_id when provided.
        """
        app_state = getattr(websocket, "application_state", None)
        client_state = getattr(websocket, "client_state", None)

        if app_state == WebSocketState.CONNECTED:
            if websocket not in self.active_connections:
                self.active_connections.append(websocket)
            if user_id:
                u_conns = self.user_connections.setdefault(str(user_id), [])
                if websocket not in u_conns:
                    u_conns.append(websocket)
            return True

        if client_state == WebSocketState.DISCONNECTED or app_state == WebSocketState.DISCONNECTED:
            logger.debug("Cannot accept WebSocket: connection already closed or disconnected.")
            return False

        try:
            await websocket.accept()
            if websocket not in self.active_connections:
                self.active_connections.append(websocket)
            if user_id:
                u_conns = self.user_connections.setdefault(str(user_id), [])
                if websocket not in u_conns:
                    u_conns.append(websocket)
            logger.info(f"WebSocket client connected. Total connections: {len(self.active_connections)}")
            return True
        except (WebSocketDisconnect, RuntimeError, Exception) as exc:
            logger.warning(f"WebSocket accept failed or client disconnected during handshake: {exc}")
            return False

    def disconnect(self, websocket: WebSocket, user_id: Optional[str] = None):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        if user_id and str(user_id) in self.user_connections:
            if websocket in self.user_connections[str(user_id)]:
                self.user_connections[str(user_id)].remove(websocket)
        else:
            for uid, conns in list(self.user_connections.items()):
                if websocket in conns:
                    conns.remove(websocket)
        logger.info(f"WebSocket client disconnected. Total connections: {len(self.active_connections)}")

    async def prune_dead_connections(self):
        dead_connections = []
        for connection in list(self.active_connections):
            try:
                await connection.send_json({"type": "PING"})
            except Exception:
                dead_connections.append(connection)

        for connection in dead_connections:
            self.disconnect(connection)

    async def send_to_user(self, user_id: Any, message: dict):
        """Send message only to active WebSocket connections for this specific user."""
        uid_str = str(user_id)
        conns = list(self.user_connections.get(uid_str, []))
        dead = []
        for conn in conns:
            try:
                await conn.send_json(message)
            except Exception:
                dead.append(conn)
        for conn in dead:
            self.disconnect(conn, user_id=uid_str)

    async def broadcast(self, message: dict):
        await self.prune_dead_connections()
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"WebSocket broadcast error: {str(e)}")
                self.disconnect(connection)

ws_manager = WebSocketConnectionManager()

class NotificationService:
    @staticmethod
    async def create_notification(
        db: AsyncSession,
        user_id: uuid.UUID,
        title: str,
        message: str,
        severity: str = "info",
        dedup_key: Optional[str] = None
    ) -> Optional[Notification]:
        # Concurrency-safe deduplication check
        if dedup_key:
            stmt = select(Notification).filter(
                Notification.user_id == user_id,
                Notification.dedup_key == dedup_key
            )
            res = await db.execute(stmt)
            existing = res.scalars().first()
            if existing:
                logger.info(f"Skipping duplicate notification for user {user_id} with dedup_key '{dedup_key}'.")
                return existing

        notification = Notification(
            id=uuid.uuid4(),
            user_id=user_id,
            title=title,
            message=message[:255],
            severity=severity,
            created_at=datetime.now(timezone.utc),
            is_read=False,
            dedup_key=dedup_key
        )
        db.add(notification)
        try:
            await db.commit()
            await db.refresh(notification)
        except Exception as e:
            await db.rollback()
            if dedup_key:
                stmt = select(Notification).filter(
                    Notification.user_id == user_id,
                    Notification.dedup_key == dedup_key
                )
                res = await db.execute(stmt)
                existing = res.scalars().first()
                if existing:
                    return existing
            logger.error(f"Failed to persist notification: {str(e)}")
            raise

        payload = {
            "type": "NOTIFICATION",
            "id": str(notification.id),
            "title": notification.title,
            "message": notification.message,
            "severity": notification.severity,
            "created_at": notification.created_at.isoformat(),
            "is_read": False,
            "dedup_key": dedup_key
        }
        # Send strictly to this user's active WebSocket sessions (prevent multi-user broadcast amplification)
        await ws_manager.send_to_user(user_id, payload)
        return notification
