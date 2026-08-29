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
from app.models.report import Report

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

def test_report_endpoints():
    report_id = uuid.uuid4()
    student_id = uuid.uuid4()
    
    mock_report = Report(
        id=report_id,
        title="West Boundary Trespass Incident Report",
        incident_type="Fence Crossing",
        student_id=student_id,
        created_at=datetime.now(timezone.utc),
        data={
            "narrative_summary": "Subject breached west fence at 14:05.",
            "student_info": {
                "name": "Alex Mercer",
                "roll_number": "CS-2026-99",
                "confidence": "high"
            },
            "explainable_breakdown": {
                "semantic": 0.85,
                "identity": 0.92,
                "appearance": 0.88,
                "temporal": 1.0,
                "zone": 1.0
            },
            "timeline": [
                {
                    "time": "14:05:10",
                    "camera": "Cam-02-Fence",
                    "description": "Crossed boundary line."
                }
            ]
        }
    )

    async def mock_execute(stmt):
        return MockSQLResult(mock_report)

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

    print("Checking POST /reports/generate...")
    response = client.post("/api/v1/reports/generate", json={
        "title": "West Boundary Trespass Incident Report",
        "incident_type": "Fence Crossing",
        "student_id": str(student_id),
        "data": mock_report.data
    })
    assert response.status_code == status.HTTP_201_CREATED

    print("Checking GET /reports...")
    response = client.get("/api/v1/reports")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "report_id" in data[0]
    assert "title" in data[0]

    print("Checking GET /reports/{id}...")
    response = client.get(f"/api/v1/reports/{report_id}")
    assert response.status_code == status.HTTP_200_OK

    print("Checking GET /reports/download/{id}...")
    response = client.get(f"/api/v1/reports/download/{report_id}?format=html")
    assert response.status_code == status.HTTP_200_OK

    print("All Report Generator API endpoints verified successfully!")

if __name__ == "__main__":
    test_report_endpoints()
