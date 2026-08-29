import uuid
import logging
from datetime import datetime, timezone
from fastapi import WebSocket
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.notification import Notification

logger = logging.getLogger(__name__)

import time
from typing import List, Dict

logger = logging.getLogger(__name__)

class WebSocketConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.reconnect_attempts: Dict[str, List[float]] = {}

    def is_rate_limited(self, ip_address: str) -> bool:
        now = time.time()
        attempts = self.reconnect_attempts.get(ip_address, [])
        attempts = [t for t in attempts if now - t < 10.0]
        self.reconnect_attempts[ip_address] = attempts

        if len(attempts) >= 5:
            return True
            
        self.reconnect_attempts[ip_address].append(now)
        return False

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket client connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
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
        severity: str = "info"
    ) -> Notification:
        notification = Notification(
            id=uuid.uuid4(),
            user_id=user_id,
            title=title,
            message=message,
            severity=severity,
            created_at=datetime.now(timezone.utc),
            is_read=False
        )
        db.add(notification)
        await db.commit()
        await db.refresh(notification)

        payload = {
            "type": "NOTIFICATION",
            "id": str(notification.id),
            "title": notification.title,
            "message": notification.message,
            "severity": notification.severity,
            "created_at": notification.created_at.isoformat(),
            "is_read": False
        }
        await ws_manager.broadcast(payload)
        return notification
