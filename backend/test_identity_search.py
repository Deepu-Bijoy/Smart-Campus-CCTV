import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Mock out heavy deep learning and client packages before app main loads
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['qdrant_client'] = MagicMock()
sys.modules['qdrant_client.http'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['insightface'] = MagicMock()
sys.modules['insightface.app'] = MagicMock()

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.main import app
from app.api import deps
from app.db.base_class import Base
from app.models.user import User
from app.models.student import Student
from app.models.camera import Camera
from app.models.video import Video
from app.models.track import Track, PersonReid
from app.models.recognition import StudentRecognitionEvent

# In-memory test database
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
engine = create_async_engine(TEST_DATABASE_URL, future=True)
TestingSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

mock_user = User(
    id=uuid.UUID("d3b7a123-4567-89ab-cdef-0123456789ab"),
    email="operator@smartcampus.com",
    hashed_password="hashedpassword123",
    full_name="Lead Security Operator",
    is_active=True
)

app.dependency_overrides[deps.get_current_user] = lambda: mock_user

async def override_get_db():
    async with TestingSessionLocal() as session:
        yield session

app.dependency_overrides[deps.get_db] = override_get_db

client = TestClient(app)

async def test_identity_pipeline():
    # 1. Initialize Tables in memory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Add data for Test Case 1: Student with appearances
    # 3. Add data for Test Case 3: Student with NO appearances
    async with TestingSessionLocal() as db:
        # Save Student 1
        student1_id = uuid.uuid4()
        student1 = Student(
            id=student1_id,
            university_roll_number="CS22B045",
            name="Deepu Bijoy",
            department="CSE",
            programme="S8 CSE",
            year=4,
            semester=8,
            section="A",
            email="deepu@smartcampus.com",
            status="active"
        )
        db.add(student1)

        # Save Student 2 (no appearances)
        student2_id = uuid.uuid4()
        student2 = Student(
            id=student2_id,
            university_roll_number="CS22B999",
            name="Alice Vance",
            department="ECE",
            programme="S8 ECE",
            year=4,
            semester=8,
            section="B",
            email="alice@smartcampus.com",
            status="active"
        )
        db.add(student2)

        # Save Camera
        camera_id = uuid.uuid4()
        camera = Camera(
            id=camera_id,
            name="Camera-GateA",
            building="Admin Block",
            floor=1,
            location="Main Gate A",
            direction="North",
            resolution="1920x1080",
            status="active"
        )
        db.add(camera)

        # Save Video
        video_id = uuid.uuid4()
        video = Video(
            id=video_id,
            title="Gate A Feed",
            filename="feed_gatea.mp4",
            original_filename="feed_gatea.mp4",
            file_path="storage/feed_gatea.mp4",
            status="completed",
            progress_percentage=100,
            uploaded_by=mock_user.id
        )
        db.add(video)

        # Save Track
        track_id = uuid.uuid4()
        track = Track(
            id=track_id,
            video_id=video_id,
            object_class="person",
            tracker_id=1,
            start_time=0.0,
            end_time=10.0
        )
        db.add(track)

        # Save PersonReid crop
        reid = PersonReid(
            id=uuid.uuid4(),
            track_id=track_id,
            video_id=video_id,
            embedding=[0.1] * 512,
            timestamp_seconds=5.0,
            crop_path="storage/crops/track_1_crop.jpg",
            camera_id=str(camera_id)
        )
        db.add(reid)

        # Save StudentRecognitionEvent for Deepu Bijoy (student1)
        event = StudentRecognitionEvent(
            id=uuid.uuid4(),
            track_id=track_id,
            student_id=student1_id,
            video_id=video_id,
            timestamp=datetime.now(timezone.utc),
            similarity_score=0.85,
            confidence="high",
            camera_id=str(camera_id)
        )
        db.add(event)

        await db.commit()

    # --- EXECUTE TEST CASE 1: Student Found with Appearances ---
    print("Testing Case 1: Searching for 'Find Deepu'...")
    response = client.post("/api/v1/investigations/search/identity", json={"query": "Find Deepu"})
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "identity"
    assert data["student"] is not None
    assert data["student"]["name"] == "Deepu Bijoy"
    assert len(data["appearances"]) == 1
    
    appearance = data["appearances"][0]
    assert appearance["camera"] == "Camera-GateA (Main Gate A)"
    assert appearance["recognition_confidence"] == 0.85
    assert appearance["evidence"]["image"] == "/storage/crops/track_1_crop.jpg"
    assert appearance["evidence"]["video"] == "/storage/feed_gatea.mp4"
    print("Case 1 passed.")

    # --- EXECUTE TEST CASE 2: Unknown Student ---
    print("Testing Case 2: Searching for 'Find Unknown Student'...")
    response = client.post("/api/v1/investigations/search/identity", json={"query": "Find Unknown Student"})
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "identity"
    assert data["student"] is None
    assert len(data["appearances"]) == 0
    print("Case 2 passed.")

    # --- EXECUTE TEST CASE 3: Student Found with NO appearances ---
    print("Testing Case 3: Searching for 'Find Alice Vance'...")
    response = client.post("/api/v1/investigations/search/identity", json={"query": "Find Alice Vance"})
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "identity"
    assert data["student"] is not None
    assert data["student"]["name"] == "Alice Vance"
    assert len(data["appearances"]) == 0
    print("Case 3 passed.")

    print("\n===============================================")
    print("[SUCCESS] IDENTITY SEARCH PIPELINE TESTS PASSED!")
    print("===============================================\n")

if __name__ == "__main__":
    asyncio.run(test_identity_pipeline())
