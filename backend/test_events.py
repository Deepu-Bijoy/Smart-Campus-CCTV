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
from app.models.event import Event

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

def test_event_engine_endpoints():
    event_id = uuid.uuid4()
    camera_id = uuid.uuid4()
    video_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    
    mock_event = Event(
        id=event_id,
        event_type="FENCE_JUMP",
        camera_id=camera_id,
        video_id=video_id,
        timestamp=datetime.now(timezone.utc),
        zone_id=zone_id,
        student_id=None,
        confidence="high",
        tracks=[]
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt).lower()
        if "event" in stmt_str:
            return MockSQLResult([mock_event])
        return MockSQLResult([])

    mock_db = MagicMock()
    mock_db.execute = mock_execute
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    print("Checking GET /events...")
    response = client.get("/api/v1/events/")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1

    print("Checking GET /events/types...")
    response = client.get("/api/v1/events/types")
    assert response.status_code == status.HTTP_200_OK
    assert "FENCE_JUMP" in response.json()

    print("Checking GET /events/video/{video_id}...")
    response = client.get(f"/api/v1/events/video/{video_id}")
    assert response.status_code == status.HTTP_200_OK

    print("Checking GET /events/{id}...")
    response = client.get(f"/api/v1/events/{event_id}")
    assert response.status_code == status.HTTP_200_OK

    print("All Event Detection API endpoints verified successfully!")

if __name__ == "__main__":
    test_event_engine_endpoints()
