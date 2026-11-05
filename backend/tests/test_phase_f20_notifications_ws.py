import os
import sys
import uuid
import time
import io
import logging
from datetime import datetime, timezone, timedelta
import unittest
import jwt
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.main import app
from app.core.config import settings
from app.core.security import create_access_token
from app.core.logging_filter import RedactTokenFilter
from app.services.notification_service import ws_manager

class TestPhaseF20NotificationsWebSocket(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        # Use existing operator/admin user ID in database
        cls.user_id = "23087cde-f8ca-4815-9769-0516754d6921"
        cls.valid_token = create_access_token(cls.user_id)
        cls.headers = {"Authorization": f"Bearer {cls.valid_token}"}

    def setUp(self):
        # Reset ws_manager rate limits before each test
        ws_manager.reconnect_attempts.clear()

    def test_1_single_managed_connection_and_ping_pong(self):
        """Verify a valid WebSocket connection connects, receives PONG, and cleans up on close."""
        initial_count = len(ws_manager.active_connections)
        with self.client.websocket_connect(f"/api/v1/notifications/ws?token={self.valid_token}") as ws:
            # Active connections must have increased by 1
            self.assertEqual(len(ws_manager.active_connections), initial_count + 1)
            # Test ping/pong
            ws.send_text("PING")
            response = ws.receive_text()
            self.assertEqual(response, "PONG")

        # After context exit, the connection should be cleaned up
        self.assertEqual(len(ws_manager.active_connections), initial_count)

    def test_2_invalid_and_expired_jwt_rejection(self):
        """Verify invalid and expired tokens are rejected with RFC code 4401 without loops."""
        # 1. Malformed token
        with self.assertRaises(WebSocketDisconnect) as cm_malformed:
            with self.client.websocket_connect("/api/v1/notifications/ws?token=not_a_valid_jwt") as ws:
                ws.receive_text()
        self.assertEqual(cm_malformed.exception.code, 4401)

        # 2. Expired token
        expired_payload = {
            "sub": self.user_id,
            "role": "operator",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=10)
        }
        expired_token = jwt.encode(expired_payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        with self.assertRaises(WebSocketDisconnect) as cm_expired:
            with self.client.websocket_connect(f"/api/v1/notifications/ws?token={expired_token}") as ws:
                ws.receive_text()
        self.assertEqual(cm_expired.exception.code, 4401)

        # 3. Nonexistent user
        fake_payload = {
            "sub": str(uuid.uuid4()),
            "role": "operator",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10)
        }
        fake_token = jwt.encode(fake_payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
        with self.assertRaises(WebSocketDisconnect) as cm_fake:
            with self.client.websocket_connect(f"/api/v1/notifications/ws?token={fake_token}") as ws:
                ws.receive_text()
        self.assertEqual(cm_fake.exception.code, 4401)

    def test_3_rate_limiting_behavior_and_success_reset(self):
        """Verify rate limiting triggers under spam and resets when a legitimate connection succeeds."""
        remote_ip = "192.168.1.100"
        
        # Remote limit is 30 in 60s
        for _ in range(30):
            limited = ws_manager.is_rate_limited(remote_ip)
            self.assertFalse(limited)

        # 31st attempt should be rate limited
        self.assertTrue(ws_manager.is_rate_limited(remote_ip))

        # Successful connection should clear strikes for that client
        ws_manager.record_successful_connection(remote_ip, user_id=self.user_id)
        # Should now be allowed again
        self.assertFalse(ws_manager.is_rate_limited(remote_ip))

    def test_4_rate_limiting_rejection_code_4429(self):
        """Verify that when rate limited, the WebSocket returns code 4429."""
        ip = "testclient"
        # Fill quota to trigger rate limiting
        for _ in range(ws_manager.MAX_LOCAL_ATTEMPTS):
            ws_manager.is_rate_limited(ip)

        self.assertTrue(ws_manager.is_rate_limited(ip))

        with self.assertRaises(WebSocketDisconnect) as cm_limited:
            with self.client.websocket_connect(f"/api/v1/notifications/ws?token={self.valid_token}") as ws:
                ws.receive_text()
        self.assertEqual(cm_limited.exception.code, 4429)

    def test_5_token_redaction_in_logging(self):
        """Verify that RedactTokenFilter masks query tokens, bearer tokens, and cookie tokens."""
        redact_filter = RedactTokenFilter()
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.addFilter(redact_filter)
        logger = logging.getLogger("test_f20_redaction")
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

        # Log query parameter
        logger.info(f"Connecting to /api/v1/notifications/ws?token={self.valid_token}&other=123")
        # Log Uvicorn access style
        logger.info('%s - "%s %s HTTP/%s" %d', '127.0.0.1:8000', 'GET', f'/api/v1/notifications/ws?token={self.valid_token}', '1.1', 101)
        # Log Bearer header
        logger.info(f"Headers: Authorization: Bearer {self.valid_token}")

        output = stream.getvalue()
        self.assertNotIn(self.valid_token, output, "Raw token must not appear in logged output")
        self.assertIn("[REDACTED]", output)

    def test_6_rest_endpoints_unaffected(self):
        """Verify that GET /api/v1/videos and GET /api/v1/notifications remain healthy and return HTTP 200."""
        # Videos endpoint
        v_resp = self.client.get("/api/v1/videos", headers=self.headers)
        self.assertEqual(v_resp.status_code, 200, f"Expected 200 for /api/v1/videos, got {v_resp.status_code}: {v_resp.text}")
        videos = v_resp.json()
        self.assertIsInstance(videos, list)

        # Notifications endpoint
        n_resp = self.client.get("/api/v1/notifications", headers=self.headers)
        self.assertEqual(n_resp.status_code, 200, f"Expected 200 for /api/v1/notifications, got {n_resp.status_code}: {n_resp.text}")
        notifications = n_resp.json()
        self.assertIsInstance(notifications, list)

if __name__ == "__main__":
    unittest.main()
