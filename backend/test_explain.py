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

def test_explain_endpoints():
    mock_results = [
        {
            "track_id": uuid.uuid4(),
            "video_id": uuid.uuid4(),
            "camera_id": "cam_1",
            "timestamp": 10.5,
            "confidence": 0.95,
            "hybrid_score": 0.85,
            "semantic_score": 0.82,
            "identity_score": 0.78,
            "temporal_score": 1.0,
            "metadata_score": 1.0
        }
    ]

    async def mock_execute(stmt):
        return MockSQLResult([])

    mock_db = MagicMock()
    mock_db.execute = mock_execute
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    with patch("app.services.hybrid_retrieval.HybridRetrievalEngine.search", return_value=mock_results):
        print("Checking POST /search/explain...")
        response = client.post("/api/v1/search/explain", json={
            "query": "person walking near the fence after 3:00 pm",
            "camera_id": "cam_1"
        })
        assert response.status_code == status.HTTP_200_OK
        res_json = response.json()
        assert len(res_json["results"]) == 1
        assert "scores" in res_json["results"][0]
        assert "reasons" in res_json["results"][0]

        print("Checking GET /search/evidence/{track_id}...")
        track_id = uuid.uuid4()
        response = client.get(f"/api/v1/search/evidence/{track_id}")
        assert response.status_code == status.HTTP_200_OK

    print("All Explainable Retrieval Engine API endpoints verified successfully!")

if __name__ == "__main__":
    test_explain_endpoints()
