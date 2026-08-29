import sys
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# 1. Mock out heavy deep learning and client packages before app main loads
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
from app.models.student import Student
from app.models.video import Video
from app.models.track import Track
from app.models.recognition import StudentRecognitionEvent

# Mock active operator user for authentication checks
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
    def scalar(self):
        return self._value if isinstance(self._value, int) else 1
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
    def scalar(self):
        return self._value if isinstance(self._value, int) else 1
    def all(self):
        return [self._value] if not isinstance(self._value, list) else self._value

def test_identification_endpoints():
    student_id = uuid.uuid4()
    video_id = uuid.uuid4()
    track_id = uuid.uuid4()
    event_id = uuid.uuid4()
    
    mock_student = Student(
        id=student_id,
        university_roll_number="UR20260401",
        name="Jane Doe",
        department="Computer Science",
        programme="B.Tech",
        year=3,
        semester=6,
        section="A",
        email="janedoe@university.edu",
        phone="+1234567890",
        status="active",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    
    mock_video = Video(
        id=video_id,
        filename="cctv_west_gate.mp4",
        original_filename="cctv_west_gate.mp4",
        file_path="storage/videos/cctv_west_gate.mp4",
        file_size=10240,
        status="completed",
        uploaded_by=uuid.uuid4(),
        created_at=datetime.now(timezone.utc)
    )
    
    mock_track = Track(
        id=track_id,
        video_id=video_id,
        object_class="person",
        tracker_id=1,
        start_time=0.0,
        end_time=10.0,
        created_at=datetime.now(timezone.utc)
    )
    
    mock_event = StudentRecognitionEvent(
        id=event_id,
        track_id=track_id,
        student_id=student_id,
        video_id=video_id,
        timestamp=datetime.now(timezone.utc),
        similarity_score=0.88,
        confidence="high",
        camera_id="Camera-WestGate"
    )

    class MockQueryResultRow:
        def __init__(self, id, name, university_roll_number, appearances_count, max_similarity):
            self.id = id
            self.name = name
            self.university_roll_number = university_roll_number
            self.appearances_count = appearances_count
            self.max_similarity = max_similarity

    async def mock_execute(stmt):
        stmt_str = str(stmt).lower()
        if "max_similarity" in stmt_str or "group_by" in stmt_str or "appearances_count" in stmt_str:
            row = MockQueryResultRow(student_id, "Jane Doe", "UR20260401", 1, 0.88)
            res = MagicMock()
            res.all.return_value = [row]
            return res
        elif "from students" in stmt_str or "students.id =" in stmt_str:
            return MockSQLResult([mock_student])
        elif "from videos" in stmt_str or "videos.id =" in stmt_str:
            return MockSQLResult([mock_video])
        elif "from tracks" in stmt_str or "tracks.id =" in stmt_str:
            return MockSQLResult([mock_track])
        elif "recognition" in stmt_str:
            return MockSQLResult([mock_event])
        return MockSQLResult(None)

    async def mock_commit():
        pass

    mock_db = MagicMock()
    mock_db.execute = mock_execute
    mock_db.commit = mock_commit
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    print("Checking GET /students/{id}/appearances...")
    response = client.get(f"/api/v1/students/{student_id}/appearances")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1
    assert response.json()[0]["similarity_score"] == 0.88

    print("Checking GET /tracks/{track_id}/identified-student...")
    response = client.get(f"/api/v1/tracks/{track_id}/identified-student")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["student_name"] == "Jane Doe"

    print("Checking GET /videos/{id}/identified-students...")
    response = client.get(f"/api/v1/videos/{video_id}/identified-students")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()[0]["appearances_count"] == 1

    print("All identification API endpoints verified successfully!")

if __name__ == "__main__":
    test_identification_endpoints()
