import asyncio
import sys
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Mock out heavy deep learning models and clients
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['insightface'] = MagicMock()
sys.modules['insightface.app'] = MagicMock()

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///:memory:"

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
TEST_DATABASE_URL = os.environ["TEST_DATABASE_URI"]
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

async def test_unified_router_pipeline():
    # 1. Initialize Tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Add relational mock data
    async with TestingSessionLocal() as db:
        student_id = uuid.uuid4()
        camera_id = uuid.uuid4()
        video_id = uuid.uuid4()
        track_id = uuid.uuid4()

        # Enrolled Student (Dipz / Deepu)
        student = Student(
            id=student_id,
            university_roll_number="CS22B045",
            name="Deepu Bijoy (Dipz)",
            department="CSE",
            programme="S8 CSE",
            year=4,
            semester=8,
            section="A",
            email="deepu@smartcampus.com",
            status="active"
        )
        db.add(student)

        # Camera
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

        # Video
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

        # Track
        track = Track(
            id=track_id,
            video_id=video_id,
            object_class="person",
            tracker_id=1,
            start_time=0.0,
            end_time=10.0
        )
        db.add(track)

        # PersonReid crop
        reid = PersonReid(
            id=uuid.uuid4(),
            track_id=track_id,
            video_id=video_id,
            embedding=[0.8] + [0.0]*511,
            timestamp_seconds=5.0,
            crop_path="storage/crops/track_1_crop.jpg",
            camera_id=str(camera_id)
        )
        db.add(reid)

        # Face Recognition Event
        event = StudentRecognitionEvent(
            id=uuid.uuid4(),
            track_id=track_id,
            student_id=student_id,
            video_id=video_id,
            timestamp=datetime.now(timezone.utc),
            similarity_score=0.85,
            confidence="high",
            camera_id=str(camera_id)
        )
        db.add(event)

        await db.commit()

    # Mock Qdrant and CLIP response lists for appearance fallback
    qdrant_mock_results = [
        {
            "score": 0.91,
            "payload": {
                "track_id": str(track_id),
                "video_id": str(video_id),
                "camera_id": "Camera-GateA",
                "timestamp": 5.0,
                "crop_path": "storage/crops/track_1_crop.jpg",
                "object_class": "person"
            }
        }
    ]

    with patch('app.services.vector_store.QdrantVectorStore.search_by_text', return_value=qdrant_mock_results), \
         patch('app.pipeline.embedder.CLIPEmbedder.get_text_embedding', return_value=[0.1]*512):

        # --- TEST 1: Find Dipz ---
        print("Testing Query 1: 'Find Dipz'...")
        res = client.post("/api/v1/investigations/search", json={"query": "Find Dipz"})
        assert res.status_code == 200
        data = res.json()
        assert data["query_type"] == "identity"
        assert len(data["results"]) == 1
        assert data["results"][0]["student"]["name"] == "Deepu Bijoy (Dipz)"
        assert data["results"][0]["confidence"] == 0.85
        assert "ArcFace" in data["results"][0]["match_reason"]
        print("Query 1 passed.")

        # --- TEST 2: student wearing white patterned shirt ---
        print("Testing Query 2: 'student wearing white patterned shirt'...")
        res = client.post("/api/v1/investigations/search", json={"query": "student wearing white patterned shirt"})
        assert res.status_code == 200
        data = res.json()
        assert data["query_type"] == "appearance"
        assert len(data["results"]) == 1
        assert data["results"][0]["student"]["name"] == "Deepu Bijoy (Dipz)" # Identity verified from DB
        assert data["results"][0]["confidence"] >= 0.85 # Combined appearance score
        assert "CLIP similarity" in data["results"][0]["match_reason"]
        print("Query 2 passed.")

        # --- TEST 3: Did anyone jump over the wall? ---
        # Mock incident query engine response since incident table empty in memory
        incident_mock_res = [{
            "id": str(uuid.uuid4()),
            "incident_type": "Boundary Crossing",
            "severity": "High",
            "camera": {"name": "Camera-GateA", "location": "Main Gate A"},
            "timestamp": {"date": "2026-07-17", "time": "22:43:55"},
            "person": {"identity_status": "Identified", "name": "Deepu Bijoy", "class_name": "S8 CSE", "roll_number": "CS22B045", "department": "CSE"},
            "confidence": {"event_confidence": 0.98, "face_confidence": 0.85, "retrieval_confidence": 0.80},
            "explanation": "Matched because trajectory crossed Fence-North boundary",
            "evidence": {"screenshot": "/storage/crops/track_1_crop.jpg", "video_clip": "/storage/feed_gatea.mp4"}
        }]
        
        with patch('app.services.investigation_service.IncidentInvestigationQueryEngine.query_incidents', return_value=incident_mock_res):
            print("Testing Query 3: 'Did anyone jump over the wall?'...")
            res = client.post("/api/v1/investigations/search", json={"query": "Did anyone jump over the wall?"})
            assert res.status_code == 200
            data = res.json()
            assert data["query_type"] == "incident"
            assert len(data["results"]) == 1
            assert data["results"][0]["student"]["name"] == "Deepu Bijoy"
            assert data["results"][0]["confidence"] == 0.98
            assert "Fence-North boundary" in data["results"][0]["match_reason"]
            print("Query 3 passed.")

        # --- TEST 4: Where was Deepu seen? ---
        print("Testing Query 4: 'Where was Deepu seen?'...")
        res = client.post("/api/v1/investigations/search", json={"query": "Where was Deepu seen?"})
        assert res.status_code == 200
        data = res.json()
        assert data["query_type"] == "identity"
        assert len(data["results"]) == 1
        print("Query 4 passed.")

        # --- TEST 5: person near gate ---
        print("Testing Query 5: 'person near gate'...")
        res = client.post("/api/v1/investigations/search", json={"query": "person near gate"})
        assert res.status_code == 200
        data = res.json()
        assert data["query_type"] == "appearance"
        assert len(data["results"]) == 1
        print("Query 5 passed.")

    print("\n==============================================")
    print("[SUCCESS] UNIFIED SEARCH ROUTER TESTS PASSED!")
    print("==============================================\n")

if __name__ == "__main__":
    asyncio.run(test_unified_router_pipeline())
