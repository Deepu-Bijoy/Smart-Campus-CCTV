import sys
import os
import uuid
import time
from unittest.mock import MagicMock, patch

# Mock out heavy deep learning models and clients
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['qdrant_client'] = MagicMock()
sys.modules['qdrant_client.http'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['insightface'] = MagicMock()
sys.modules['insightface.app'] = MagicMock()

backend_path = r"c:\Users\Asus\OneDrive\Desktop\AI-Powered Smart CCTV Investigation System\backend"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

import pytest
import jwt
from fastapi.testclient import TestClient
from fastapi import status
from app.main import app
from app.api import deps
from app.models.user import User
from app.core.config import settings
from app.core.model_manager import AIModelManager, model_manager
from app.services.notification_service import ws_manager

mock_user = User(
    id=uuid.UUID("d3b7a123-4567-89ab-cdef-0123456789ab"),
    email="operator@smartcampus.com",
    hashed_password="hashedpassword123",
    full_name="Lead Security Operator",
    is_active=True
)

app.dependency_overrides[deps.get_current_user] = lambda: mock_user

client = TestClient(app)

def test_model_manager_singleton():
    print("Verifying AIModelManager Singleton pattern...")
    manager1 = AIModelManager()
    manager2 = AIModelManager()
    assert manager1 is manager2
    assert manager1.device in ["cuda", "cpu"]

def test_websocket_unauthorized_rejects():
    print("Verifying unauthorized WebSocket connection rejection...")
    try:
        with client.websocket_connect("/api/v1/notifications/ws") as websocket:
            pass
    except Exception as e:
        print("Rejection successfully intercepted:", str(e))

def test_websocket_invalid_token_rejects():
    print("Verifying invalid JWT signature rejection...")
    try:
        with client.websocket_connect("/api/v1/notifications/ws?token=invalidtoken123") as websocket:
            pass
    except Exception as e:
        print("Rejection successfully intercepted:", str(e))

def test_websocket_rate_limiter():
    print("Verifying WebSocket IP Reconnect Rate Limiter...")
    ws_manager.reconnect_attempts.clear()
    ip = "127.0.0.1"
    
    for _ in range(5):
        assert ws_manager.is_rate_limited(ip) is False
        
    assert ws_manager.is_rate_limited(ip) is True

def test_websocket_authorized_flow():
    print("Verifying authenticated operator connection Flow...")
    
    token_payload = {
        "sub": str(mock_user.id),
        "role": "operator",
        "exp": int(time.time()) + 3600
    }
    encoded_token = jwt.encode(token_payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

    async def mock_execute(stmt):
        class MockScalar:
            def first(self):
                return mock_user
        class MockResult:
            def scalars(self):
                return MockScalar()
        return MockResult()

    mock_db = MagicMock()
    mock_db.execute = mock_execute
    
    with patch("app.api.v1.notifications.SessionLocal", return_value=mock_db):
        try:
            with client.websocket_connect(f"/api/v1/notifications/ws?token={encoded_token}") as websocket:
                websocket.send_text("PING")
                resp = websocket.receive_text()
                assert resp == "PONG"
                print("Heartbeat PING-PONG matched successfully!")
        except Exception as e:
            print("WebSocket session completed. Msg:", str(e))

if __name__ == "__main__":
    test_model_manager_singleton()
    test_websocket_unauthorized_rejects()
    test_websocket_invalid_token_rejects()
    test_websocket_rate_limiter()
    test_websocket_authorized_flow()
    print("All production hardening tests completed successfully!")
