import sys
import os
import uuid
import numpy as np
from unittest.mock import MagicMock, patch

# 1. Mock out heavy deep learning and client packages before app main loads
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['qdrant_client'] = MagicMock()
sys.modules['qdrant_client.http'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['insightface'] = MagicMock()
sys.modules['insightface.app'] = MagicMock()

# Add backend to sys.path using direct absolute path
backend_path = r"c:\Users\Asus\OneDrive\Desktop\AI-Powered Smart CCTV Investigation System\backend"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from fastapi import status
from app.main import app
from app.api import deps
from app.models.user import User
from app.models.student import Student, StudentPhoto, StudentFaceSession
from app.models.face_embedding import StudentFaceEmbedding

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

def test_enrollment_pipeline():
    student_id = uuid.uuid4()
    photo_id = uuid.uuid4()
    
    mock_student = Student(
        id=student_id,
        university_roll_number="UR20260402",
        name="Jane Doe",
        department="Computer Science",
        programme="B.Tech",
        year=3,
        semester=6,
        section="A",
        email="janedoe@university.edu"
    )

    mock_photo = StudentPhoto(
        id=photo_id,
        student_id=student_id,
        photo_path="storage/students/test_photo.jpg",
        view="front",
        file_size=1024,
        mime_type="image/jpeg",
        md5_hash="hash123"
    )

    mock_session = StudentFaceSession(
        id=uuid.uuid4(),
        student_id=student_id,
        status="pending"
    )

    mock_embedding = StudentFaceEmbedding(
        id=uuid.uuid4(),
        student_id=student_id,
        photo_id=photo_id,
        embedding=[0.1] * 512,
        quality_score=0.92,
        blur_score=120.0,
        pose_yaw=0.0,
        pose_pitch=0.0,
        pose_roll=0.0,
        face_bbox={"x1": 10.0, "y1": 10.0, "x2": 100.0, "y2": 100.0}
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt).lower()
        print("MOCK EXECUTE STMT:", stmt_str)
        if "student_photos" in stmt_str or "studentphoto" in stmt_str:
            return MockSQLResult([mock_photo])
        elif "student_face_sessions" in stmt_str or "studentfacesession" in stmt_str:
            return MockSQLResult(mock_session)
        elif "student_face_embeddings" in stmt_str or "studentfaceembedding" in stmt_str:
            if "where" in stmt_str and "photo_id" in stmt_str.split("where")[-1]:
                return MockSQLResult([])
            return MockSQLResult([mock_embedding])
        return MockSQLResult(mock_student)

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

    mock_engine_res = {
        "success": True,
        "embedding": [0.1] * 512,
        "quality_score": 0.95,
        "blur_score": 120.0,
        "pose": (0.0, 0.0, 0.0),
        "bbox": [10.0, 10.0, 100.0, 100.0]
    }

    with patch("app.api.v1.students.FaceEnrollmentEngine") as mock_engine_class, \
         patch("app.api.v1.students.QdrantVectorStore") as mock_qdrant_class:
         
        mock_engine = MagicMock()
        mock_engine.process_photo.return_value = mock_engine_res
        mock_engine.model_name = "buffalo_l"
        mock_engine_class.return_value = mock_engine

        mock_qdrant = MagicMock()
        mock_qdrant.client.search.return_value = []
        mock_qdrant_class.return_value = mock_qdrant

        print("Testing POST /students/{id}/enroll...")
        response = client.post(f"/api/v1/students/{student_id}/enroll")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["processed"] == 1
        assert data["successful"] == 1
        assert data["failed"] == 0

        print("Testing GET /students/{id}/enrollment-status...")
        response = client.get(f"/api/v1/students/{student_id}/enrollment-status")
        print("Enrollment Status Response:", response.json())
        assert response.status_code == status.HTTP_200_OK
        status_data = response.json()
        assert status_data["embeddings_count"] == 1
        assert "front" in status_data["enrolled_views"]

        print("Complete Student Enrollment workflow verified successfully!")

if __name__ == "__main__":
    test_enrollment_pipeline()
