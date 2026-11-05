import os
import sys
import uuid
import logging
from datetime import datetime, timezone, timedelta
import pytest
import jwt
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketState, WebSocketDisconnect

backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.main import app
from app.core.config import settings
from app.core import security
from app.db.session import SessionLocal
from app.models.user import User
from app.models.camera import Camera
from app.models.incident import Incident
from app.services.notification_service import ws_manager
from app.api import deps
from sqlalchemy import select

client = TestClient(app)

async def _get_active_admin_token() -> tuple[str, uuid.UUID]:
    """Retrieve or generate valid access token for active admin user."""
    async with SessionLocal() as db:
        res = await db.execute(select(User).filter(User.is_active == True, User.role == "admin"))
        user = res.scalars().first()
        if not user:
            res = await db.execute(select(User).filter(User.is_active == True))
            user = res.scalars().first()
        assert user is not None, "At least one active user must exist in database"
        token = security.create_access_token(user.id)
        return token, user.id

# ---------------------------------------------------------------------------
# EVENTS REGRESSION SUITE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_01_existing_event_returns_200():
    """Verify that requesting an existing incident/event returns HTTP 200."""
    token, user_id = await _get_active_admin_token()
    temp_incident_id = uuid.uuid4()
    async with SessionLocal() as db:
        cam_res = await db.execute(select(Camera))
        cam = cam_res.scalars().first()
        cam_id = cam.id if cam else None

        inc = Incident(
            id=temp_incident_id,
            camera_id=cam_id,
            incident_type="Fight",
            confidence=0.92,
            timestamp=datetime.now(timezone.utc),
            explanation="Test incident altercation."
        )
        db.add(inc)
        await db.commit()

    try:
        resp = client.get(
            f"/api/v1/events/{temp_incident_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["id"] == str(temp_incident_id)
        assert data["event_type"] == "FIGHT"
    finally:
        async with SessionLocal() as db:
            del_inc = await db.execute(select(Incident).filter(Incident.id == temp_incident_id))
            obj = del_inc.scalars().first()
            if obj:
                await db.delete(obj)
                await db.commit()

@pytest.mark.anyio
async def test_02_missing_event_returns_404():
    """Verify that requesting a nonexistent event ID returns HTTP 404 with Event not found."""
    token, _ = await _get_active_admin_token()
    nonexistent_id = uuid.uuid4()
    resp = client.get(
        f"/api/v1/events/{nonexistent_id}",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 404
    data = resp.json()
    assert data.get("detail") == "Event not found."

@pytest.mark.anyio
async def test_03_missing_event_does_not_log_transaction_exception(caplog):
    """
    Verify that an HTTPException(404) does not trigger 'Transaction exception'
    error logging in get_db, and rolls back cleanly.
    """
    with caplog.at_level(logging.ERROR, logger="app.api.deps"):
        gen = deps.get_db()
        session = await gen.__anext__()
        try:
            # Simulate route raising 404
            raise HTTPException(status_code=404, detail="Event not found.")
        except HTTPException as exc:
            try:
                await gen.athrow(exc)
            except HTTPException:
                pass
        
        # Verify no transaction exception errors were logged
        records = [r for r in caplog.records if "Transaction exception" in r.message]
        assert len(records) == 0, f"Unexpected transaction exception logged: {[r.message for r in records]}"

@pytest.mark.anyio
async def test_04_valid_event_accessible_after_unrelated_event_deletion():
    """Verify that deleting one incident leaves another incident completely accessible with 200."""
    token, _ = await _get_active_admin_token()
    inc_a_id = uuid.uuid4()
    inc_b_id = uuid.uuid4()

    async with SessionLocal() as db:
        cam_res = await db.execute(select(Camera))
        cam = cam_res.scalars().first()
        cam_id = cam.id if cam else None

        inc_a = Incident(
            id=inc_a_id,
            camera_id=cam_id,
            incident_type="Fight",
            confidence=0.88,
            timestamp=datetime.now(timezone.utc),
            explanation="Incident A to be deleted."
        )
        inc_b = Incident(
            id=inc_b_id,
            camera_id=cam_id,
            incident_type="Fence Jump",
            confidence=0.91,
            timestamp=datetime.now(timezone.utc),
            explanation="Incident B to be preserved."
        )
        db.add_all([inc_a, inc_b])
        await db.commit()

    try:
        # Delete Incident A via admin API
        del_resp = client.delete(
            f"/api/v1/events/{inc_a_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert del_resp.status_code == 200

        # Incident A now returns 404
        resp_a = client.get(
            f"/api/v1/events/{inc_a_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp_a.status_code == 404

        # Incident B remains accessible and returns 200
        resp_b = client.get(
            f"/api/v1/events/{inc_b_id}",
            headers={"Authorization": f"Bearer {token}"}
        )
        assert resp_b.status_code == 200
        data_b = resp_b.json()
        assert data_b["id"] == str(inc_b_id)
        assert data_b["event_type"] == "FENCE_JUMP"
    finally:
        async with SessionLocal() as db:
            for target_id in [inc_a_id, inc_b_id]:
                del_q = await db.execute(select(Incident).filter(Incident.id == target_id))
                o = del_q.scalars().first()
                if o:
                    await db.delete(o)
            await db.commit()

# ---------------------------------------------------------------------------
# WEBSOCKET REGRESSION SUITE
# ---------------------------------------------------------------------------

@pytest.mark.anyio
async def test_05_ws_valid_authenticated_client_connects():
    """Verify that a client with a valid JWT connects and can exchange PING/PONG."""
    token, _ = await _get_active_admin_token()
    with client.websocket_connect(f"/api/v1/notifications/ws?token={token}") as ws:
        ws.send_text("PING")
        reply = ws.receive_text()
        assert reply == "PONG"

def test_06_ws_invalid_or_expired_jwt_rejected():
    """Verify that invalid or expired JWTs are rejected immediately with WS policy violation."""
    # 1. Invalid token
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/notifications/ws?token=invalid.tampered.token"):
            pass

    # 2. Expired token
    expired_token = security.create_access_token(
        uuid.uuid4(),
        expires_delta=timedelta(minutes=-30)
    )
    with pytest.raises(Exception):
        with client.websocket_connect(f"/api/v1/notifications/ws?token={expired_token}"):
            pass

@pytest.mark.anyio
async def test_07_ws_connection_accepted_at_most_once():
    """
    Verify that calling connect on an already CONNECTED websocket
    does not call accept again.
    """
    class MockWebSocket:
        def __init__(self):
            self.application_state = WebSocketState.CONNECTING
            self.client_state = WebSocketState.CONNECTING
            self.accept_call_count = 0

        async def accept(self):
            self.accept_call_count += 1
            self.application_state = WebSocketState.CONNECTED
            self.client_state = WebSocketState.CONNECTED

    mock_ws = MockWebSocket()
    user_id = str(uuid.uuid4())

    # First connect: should call accept
    ok1 = await ws_manager.connect(mock_ws, user_id=user_id)
    assert ok1 is True
    assert mock_ws.accept_call_count == 1

    # Second connect with same instance (state CONNECTED): should NOT call accept again
    ok2 = await ws_manager.connect(mock_ws, user_id=user_id)
    assert ok2 is True
    assert mock_ws.accept_call_count == 1, "accept must not be called a second time"

    ws_manager.disconnect(mock_ws, user_id=user_id)

@pytest.mark.anyio
async def test_08_ws_disconnect_during_handshake_safe():
    """
    Verify that if the client disconnects during the handshake or accept raises,
    connect handles it cleanly and returns False without unhandled exceptions.
    """
    class DisconnectingWebSocket:
        def __init__(self):
            self.application_state = WebSocketState.CONNECTING
            self.client_state = WebSocketState.CONNECTING

        async def accept(self):
            self.client_state = WebSocketState.DISCONNECTED
            raise WebSocketDisconnect(code=1006)

    mock_ws = DisconnectingWebSocket()
    ok = await ws_manager.connect(mock_ws, user_id=str(uuid.uuid4()))
    assert ok is False
    assert mock_ws not in ws_manager.active_connections

    # Attempting to connect an already disconnected websocket returns False immediately
    mock_ws.application_state = WebSocketState.DISCONNECTED
    ok2 = await ws_manager.connect(mock_ws, user_id=str(uuid.uuid4()))
    assert ok2 is False

@pytest.mark.anyio
async def test_09_ws_multiple_reconnects_no_stale_leaks():
    """Verify that multiple reconnects prune dead connections and do not leak memory."""
    user_id = str(uuid.uuid4())

    class StubWebSocket:
        def __init__(self, idx: int):
            self.idx = idx
            self.application_state = WebSocketState.CONNECTING
            self.client_state = WebSocketState.CONNECTING

        async def accept(self):
            self.application_state = WebSocketState.CONNECTED
            self.client_state = WebSocketState.CONNECTED

    s1 = StubWebSocket(1)
    s2 = StubWebSocket(2)
    s3 = StubWebSocket(3)

    await ws_manager.connect(s1, user_id=user_id)
    # s1 disconnects
    s1.application_state = WebSocketState.DISCONNECTED

    # s2 connects - should prune s1
    await ws_manager.connect(s2, user_id=user_id)
    conns_user = ws_manager.user_connections.get(user_id, [])
    assert s1 not in conns_user
    assert s2 in conns_user

    # s2 disconnects, s3 connects
    s2.application_state = WebSocketState.DISCONNECTED
    await ws_manager.connect(s3, user_id=user_id)
    conns_user = ws_manager.user_connections.get(user_id, [])
    assert s2 not in conns_user
    assert s3 in conns_user
    assert len(conns_user) == 1

    ws_manager.disconnect(s3, user_id=user_id)
    assert user_id not in ws_manager.user_connections

@pytest.mark.anyio
async def test_10_ws_notification_routed_strictly_to_target_user():
    """Verify that notifications are dispatched strictly to target user's active WebSocket sessions."""
    class RecordingWebSocket:
        def __init__(self, user_label: str):
            self.user_label = user_label
            self.application_state = WebSocketState.CONNECTED
            self.client_state = WebSocketState.CONNECTED
            self.received = []

        async def send_json(self, data):
            self.received.append(data)

    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()

    ws_a = RecordingWebSocket("User A")
    ws_b = RecordingWebSocket("User B")

    await ws_manager.connect(ws_a, user_id=str(user_a_id))
    await ws_manager.connect(ws_b, user_id=str(user_b_id))

    try:
        msg = {"type": "NOTIFICATION", "title": "Confidential Alert for User A", "message": "Details..."}
        await ws_manager.send_to_user(user_a_id, msg)

        assert len(ws_a.received) == 1
        assert ws_a.received[0]["title"] == "Confidential Alert for User A"
        assert len(ws_b.received) == 0, "User B must not receive User A's private notification"
    finally:
        ws_manager.disconnect(ws_a, user_id=str(user_a_id))
        ws_manager.disconnect(ws_b, user_id=str(user_b_id))
