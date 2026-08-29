import sys
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Mock out heavy deep learning and client packages before app main loads
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['qdrant_client'] = MagicMock()
sys.modules['qdrant_client.http'] = MagicMock()
sys.modules['transformers'] = MagicMock()

# Add backend to sys.path using direct absolute path
backend_path = r"c:\Users\Asus\OneDrive\Desktop\AI-Powered Smart CCTV Investigation System\backend"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from fastapi import status
from app.main import app
from app.api import deps
from app.models.user import User
from app.models.notification import Notification, NotificationPreference

mock_user = User(
    id=uuid.UUID("d3b7a123-4567-89ab-cdef-0123456789ab"),
    email="operator@smartcampus.com",
    hashed_password="hashedpassword123",
    full_name="Lead Security Operator",
    is_active=True
)

app.dependency_overrides[deps.get_current_user] = lambda: mock_user

client = TestClient(app)

class MockScalarResult:
    def __init__(self, value):
        self._value = value
    def first(self):
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value
    def all(self):
        return [self._value] if not isinstance(self._value, list) else self._value

class MockSQLResult:
    def __init__(self, value):
        self._value = value
    def scalars(self):
        return MockScalarResult(self._value)
    def all(self):
        return [self._value] if not isinstance(self._value, list) else self._value

def test_notification_endpoints():
    noti_id = uuid.uuid4()
    
    mock_noti = Notification(
        id=noti_id,
        user_id=mock_user.id,
        title="Fence Intrusion Alert",
        message="Subject jumped boundary fence at Gate 1.",
        severity="critical",
        is_read=False,
        created_at=datetime.now(timezone.utc)
    )

    mock_pref = NotificationPreference(
        id=uuid.uuid4(),
        user_id=mock_user.id,
        email_notifications=True,
        push_notifications=True,
        min_severity="info"
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt).lower()
        if "preference" in stmt_str:
            return MockSQLResult(mock_pref)
        return MockSQLResult([mock_noti])

    async def mock_commit():
        pass

    async def mock_refresh(obj):
        pass

    mock_db = MagicMock()
    mock_db.execute = mock_execute
    mock_db.add = lambda x: None
    mock_db.commit = mock_commit
    mock_db.refresh = mock_refresh
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    print("Checking GET /notifications...")
    response = client.get("/api/v1/notifications/")
    assert response.status_code == status.HTTP_200_OK

    print("Checking PUT /notifications/{id}/read...")
    response = client.put(f"/api/v1/notifications/{noti_id}/read")
    assert response.status_code == status.HTTP_200_OK

    print("Checking PUT /notifications/read-all...")
    response = client.put("/api/v1/notifications/read-all")
    assert response.status_code == status.HTTP_200_OK

    print("Checking GET /notifications/preferences...")
    response = client.get("/api/v1/notifications/preferences")
    assert response.status_code == status.HTTP_200_OK

    print("Checking PUT /notifications/preferences...")
    response = client.put("/api/v1/notifications/preferences", json={
        "email_notifications": False
    })
    assert response.status_code == status.HTTP_200_OK

    print("All Notification Alert API endpoints verified successfully!")

if __name__ == "__main__":
    test_notification_endpoints()
