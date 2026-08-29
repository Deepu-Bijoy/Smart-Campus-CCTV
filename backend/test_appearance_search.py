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

async def test_appearance_pipeline():
    # 1. Initialize Tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    track1_id = uuid.uuid4()
    track2_id = uuid.uuid4()
    student1_id = uuid.uuid4()
    camera_id = uuid.uuid4()
    video_id = uuid.uuid4()

    # 2. Add relational mock data
    async with TestingSessionLocal() as db:
        # Enrolled Student
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

        # Tracks
        track1 = Track(
            id=track1_id,
            video_id=video_id,
            object_class="person",
            tracker_id=1,
            start_time=0.0,
            end_time=10.0
        )
        db.add(track1)

        track2 = Track(
            id=track2_id,
            video_id=video_id,
            object_class="person",
            tracker_id=2,
            start_time=0.0,
            end_time=10.0
        )
        db.add(track2)

        # PersonReid features for OSNet visual comparisons
        reid1 = PersonReid(
            id=uuid.uuid4(),
            track_id=track1_id,
            video_id=video_id,
            embedding=[0.8] + [0.0]*511, # Prototype vector similarity
            timestamp_seconds=5.0,
            crop_path="storage/crops/track_1_crop.jpg",
            camera_id=str(camera_id)
        )
        db.add(reid1)

        reid2 = PersonReid(
            id=uuid.uuid4(),
            track_id=track2_id,
            video_id=video_id,
            embedding=[0.4] + [0.0]*511, # Lower visual Re-ID similarity
            timestamp_seconds=6.0,
            crop_path="storage/crops/track_2_crop.jpg",
            camera_id=str(camera_id)
        )
        db.add(reid2)

        # Verified ArcFace Biometric Recognition for Track 1 only (Deepu Bijoy)
        event = StudentRecognitionEvent(
            id=uuid.uuid4(),
            track_id=track1_id,
            student_id=student1_id,
            video_id=video_id,
            timestamp=datetime.now(timezone.utc),
            similarity_score=0.85,
            confidence="high",
            camera_id=str(camera_id)
        )
        db.add(event)

        await db.commit()

    # Mock Qdrant and CLIP response lists
    qdrant_mock_results = [
        # Two matching frames for Track 1 (should deduplicate)
        {
            "score": 0.91,
            "payload": {
                "track_id": str(track1_id),
                "video_id": str(video_id),
                "camera_id": "Camera-GateA",
                "timestamp": 5.0,
                "crop_path": "storage/crops/track_1_crop.jpg",
                "object_class": "person"
            }
        },
        {
            "score": 0.88, # Lower score for same track
            "payload": {
                "track_id": str(track1_id),
                "video_id": str(video_id),
                "camera_id": "Camera-GateA",
                "timestamp": 5.2,
                "crop_path": "storage/crops/track_1_crop_alt.jpg",
                "object_class": "person"
            }
        },
        # One matching frame for Track 2 (Unknown Person)
        {
            "score": 0.82,
            "payload": {
                "track_id": str(track2_id),
                "video_id": str(video_id),
                "camera_id": "Camera-GateA",
                "timestamp": 6.0,
                "crop_path": "storage/crops/track_2_crop.jpg",
                "object_class": "person"
            }
        }
    ]

    with patch('app.services.vector_store.QdrantVectorStore.search_by_text', return_value=qdrant_mock_results), \
         patch('app.pipeline.embedder.CLIPEmbedder.get_text_embedding', return_value=[0.1]*512):

        # --- EXECUTE TEST CASE 1 & 2: Search visual description ---
        print("Testing Case 1 & 2: Searching for 'student wearing white patterned shirt'...")
        response = client.post("/api/v1/investigations/search/appearance", json={"query": "student wearing white patterned shirt"})
        assert response.status_code == 200
        data = response.json()
        assert data["type"] == "appearance"
        assert data["query"] == "student wearing white patterned shirt"
        
        # Deduplication check: 3 matching frames must group into exactly 2 unique tracks
        assert len(data["results"]) == 2
        
        # Track 1 (Identified as Deepu Bijoy)
        track1_res = [r for r in data["results"] if r["track_id"] == str(track1_id)][0]
        assert track1_res["identity_status"] == "Identified"
        assert track1_res["student"] is not None
        assert track1_res["student"]["name"] == "Deepu Bijoy"
        assert track1_res["semantic_score"] == 0.91 # Kept highest frame score
        assert track1_res["face_confidence"] == 0.85
        assert track1_res["evidence"]["image"] == "/storage/crops/track_1_crop.jpg"
        assert track1_res["evidence"]["video"] == "/storage/feed_gatea.mp4"
        
        # Track 2 (Unknown Person)
        track2_res = [r for r in data["results"] if r["track_id"] == str(track2_id)][0]
        assert track2_res["identity_status"] == "Unknown Person"
        assert track2_res["student"] is None
        assert track2_res["semantic_score"] == 0.82
        assert track2_res["face_confidence"] == 0.0
        
        # Ranking check: Track 1 should be ranked higher due to visual scores + bonus
        assert data["results"][0]["track_id"] == str(track1_id)
        print("Case 1 & 2 passed.")

        # --- EXECUTE TEST CASE 4: Random Object (No Matches) ---
        print("Testing Case 4: Random Object (Empty Results)...")
        with patch('app.services.vector_store.QdrantVectorStore.search_by_text', return_value=[]):
            response = client.post("/api/v1/investigations/search/appearance", json={"query": "random object"})
            assert response.status_code == 200
            data = response.json()
            assert len(data["results"]) == 0
            print("Case 4 passed.")

    print("\n=================================================")
    print("[SUCCESS] APPEARANCE SEARCH PIPELINE TESTS PASSED!")
    print("=================================================\n")

if __name__ == "__main__":
    asyncio.run(test_appearance_pipeline())
