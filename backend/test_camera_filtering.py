import asyncio
import sys
import os
import uuid
from unittest.mock import MagicMock

# Gracefully mock out heavy packages not needed for this API validation
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['insightface'] = MagicMock()
sys.modules['insightface.app'] = MagicMock()

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Enable isolated database and testing environment
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///:memory:"

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.main import app
from app.api import deps
from app.db.base_class import Base
from app.models.user import User
from app.models.student import Student
from app.models.camera import Camera
from app.models.video import Video
from app.models.track import PersonReid
from app.models.recognition import StudentRecognitionEvent
from app.models.incident import Incident
from app.services.vector_store import QdrantVectorStore
from qdrant_client.http import models as qdrant_models

TEST_DATABASE_URL = os.environ["TEST_DATABASE_URI"]
engine = create_async_engine(TEST_DATABASE_URL, future=True)
TestingSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False
)

mock_user = User(
    id=uuid.uuid4(),
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

# Mock embedder text embeddings for appearance queries
class MockEmbedder:
    def get_text_embedding(self, text):
        return [0.1] * 512

async def run_tests():
    # 1. Initialize Tables in memory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    qdrant_store = QdrantVectorStore()
    
    # 2. Seed Data
    cam1_id = uuid.uuid4()
    cam2_id = uuid.uuid4()
    student_id = uuid.uuid4()
    
    async with TestingSessionLocal() as db:
        # Create User
        db.add(mock_user)
        await db.commit()
        
        # Create Cameras
        cam1 = Camera(
            id=cam1_id,
            name="Gate A",
            building="Main Gate",
            floor=0,
            location="Main Entrance",
            direction="in",
            resolution="1920x1080"
        )
        cam2 = Camera(
            id=cam2_id,
            name="Parking",
            building="North Block",
            floor=0,
            location="Student Parking Lot",
            direction="west",
            resolution="1920x1080"
        )
        db.add_all([cam1, cam2])
        
        # Create Student
        student = Student(
            id=student_id,
            university_roll_number="UR2026101",
            name="Dipz",
            department="CSE",
            programme="B.Tech",
            year=4,
            semester=8,
            section="A",
            email="dipz@cse.edu",
            embedding_generated=True
        )
        db.add(student)
        await db.commit()
        
        # Create mock Videos
        vid1 = Video(
            id=uuid.uuid4(),
            title="Video Gate A",
            filename="gate_a.mp4",
            original_filename="gate_a.mp4",
            file_path="storage/videos/gate_a.mp4",
            status="completed",
            uploaded_by=mock_user.id,
            camera_id=cam1_id
        )
        vid2 = Video(
            id=uuid.uuid4(),
            title="Video Parking",
            filename="parking.mp4",
            original_filename="parking.mp4",
            file_path="storage/videos/parking.mp4",
            status="completed",
            uploaded_by=mock_user.id,
            camera_id=cam2_id
        )
        db.add_all([vid1, vid2])
        await db.commit()
        
        # Create Recognition Events
        rec1 = StudentRecognitionEvent(
            id=uuid.uuid4(),
            student_id=student_id,
            video_id=vid1.id,
            track_id=uuid.uuid4(),
            camera_id=str(cam1_id),
            similarity_score=0.92,
            confidence=0.92
        )
        rec2 = StudentRecognitionEvent(
            id=uuid.uuid4(),
            student_id=student_id,
            video_id=vid2.id,
            track_id=uuid.uuid4(),
            camera_id=str(cam2_id),
            similarity_score=0.88,
            confidence=0.88
        )
        db.add_all([rec1, rec2])
        
        # Create Incidents
        inc1 = Incident(
            id=uuid.uuid4(),
            incident_type="Boundary Crossing",
            camera_id=cam1_id,
            confidence=0.95,
            explanation="Person jumped over boundary wall near Gate A"
        )
        inc2 = Incident(
            id=uuid.uuid4(),
            incident_type="Boundary Crossing",
            camera_id=cam2_id,
            confidence=0.91,
            explanation="Person jumped over boundary wall near Parking Lot"
        )
        db.add_all([inc1, inc2])
        await db.commit()

        # Create Track Crops
        reid1 = PersonReid(
            id=uuid.uuid4(),
            track_id=rec1.track_id,
            video_id=vid1.id,
            crop_path="storage/crops/rec1.jpg",
            embedding=[0.1]*512,
            timestamp_seconds=10.0
        )
        reid2 = PersonReid(
            id=uuid.uuid4(),
            track_id=rec2.track_id,
            video_id=vid2.id,
            crop_path="storage/crops/rec2.jpg",
            embedding=[0.1]*512,
            timestamp_seconds=20.0
        )
        db.add_all([reid1, reid2])
        await db.commit()

    # Seed Qdrant points for Appearance queries
    qdrant_store.client.upsert(
        collection_name=qdrant_store.collection_name,
        points=[
            qdrant_models.PointStruct(
                id=str(uuid.uuid4()),
                vector=[0.1] * 512,
                payload={
                    "video_id": str(vid1.id),
                    "track_id": str(rec1.track_id),
                    "camera_id": str(cam1_id),
                    "object_class": "person"
                }
            ),
            qdrant_models.PointStruct(
                id=str(uuid.uuid4()),
                vector=[0.1] * 512,
                payload={
                    "video_id": str(vid2.id),
                    "track_id": str(rec2.track_id),
                    "camera_id": str(cam2_id),
                    "object_class": "person"
                }
            )
        ]
    )

    print("=====================================================")
    print("STARTING E2E CAMERA FILTERING SEARCH TESTS")
    print("=====================================================")

    # Mock text embedder globally inside dependencies for appearance search
    from unittest.mock import patch
    patcher = patch("app.pipeline.embedder.CLIPEmbedder", return_value=MockEmbedder())
    patcher.start()

    # ----------------------------------------------------
    # TEST 1: Gate A, Query "Find Dipz"
    # ----------------------------------------------------
    print("\nRunning Test 1: Query 'Find Dipz' filtered by Gate A...")
    response = client.post("/api/v1/investigations/search", json={
        "query": "Find Dipz",
        "camera_id": str(cam1_id)
    })
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["query_type"] == "identity"
    print(f"  Received: {len(res_data['results'])} occurrences.")
    assert len(res_data["results"]) == 1
    assert "Gate A" in res_data["results"][0]["camera"]
    print("  [SUCCESS] Filtered correctly to only Gate A.")

    # ----------------------------------------------------
    # TEST 2: All Cameras, Query "Find Dipz"
    # ----------------------------------------------------
    print("\nRunning Test 2: Query 'Find Dipz' filtered by All Cameras...")
    response = client.post("/api/v1/investigations/search", json={
        "query": "Find Dipz",
        "camera_id": None
    })
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["query_type"] == "identity"
    print(f"  Received: {len(res_data['results'])} occurrences.")
    assert len(res_data["results"]) == 2
    cameras_matched = [r["camera"] for r in res_data["results"]]
    assert any("Gate A" in c for c in cameras_matched)
    assert any("Parking" in c for c in cameras_matched)
    print("  [SUCCESS] Returned results from all cameras.")

    # ----------------------------------------------------
    # TEST 3: Parking, Query "Did anyone jump wall?"
    # ----------------------------------------------------
    print("\nRunning Test 3: Query 'Did anyone jump wall?' filtered by Parking...")
    response = client.post("/api/v1/investigations/search", json={
        "query": "Did anyone jump wall?",
        "camera_id": str(cam2_id)
    })
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["query_type"] == "incident"
    print(f"  Received: {len(res_data['results'])} incidents.")
    assert len(res_data["results"]) == 1
    assert "Parking" in res_data["results"][0]["camera"]
    print("  [SUCCESS] Filtered correctly to only Parking incident.")

    # ----------------------------------------------------
    # TEST 4: All Cameras, Query "Did anyone jump wall?"
    # ----------------------------------------------------
    print("\nRunning Test 4: Query 'Did anyone jump wall?' filtered by All Cameras...")
    response = client.post("/api/v1/investigations/search", json={
        "query": "Did anyone jump wall?",
        "camera_id": None
    })
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["query_type"] == "incident"
    print(f"  Received: {len(res_data['results'])} incidents.")
    assert len(res_data["results"]) == 2
    print("  [SUCCESS] Returned incidents from both cameras.")

    # ----------------------------------------------------
    # TEST 5: Gate A, Query "student wearing white patterned shirt" (Appearance)
    # ----------------------------------------------------
    print("\nRunning Test 5: Query 'student wearing white patterned shirt' filtered by Gate A...")
    response = client.post("/api/v1/investigations/search", json={
        "query": "student wearing white patterned shirt",
        "camera_id": str(cam1_id)
    })
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["query_type"] == "appearance"
    print(f"  Received: {len(res_data['results'])} matches.")
    assert len(res_data["results"]) == 1
    assert "Gate A" in res_data["results"][0]["camera"]
    print("  [SUCCESS] Filtered correctly to only Gate A appearance tracks.")

    # ----------------------------------------------------
    # TEST 6: All Cameras, Query "student wearing white patterned shirt" (Appearance)
    # ----------------------------------------------------
    print("\nRunning Test 6: Query 'student wearing white patterned shirt' filtered by All Cameras...")
    response = client.post("/api/v1/investigations/search", json={
        "query": "student wearing white patterned shirt",
        "camera_id": None
    })
    assert response.status_code == 200
    res_data = response.json()
    assert res_data["query_type"] == "appearance"
    print(f"  Received: {len(res_data['results'])} matches.")
    assert len(res_data["results"]) == 2
    print("  [SUCCESS] Returned appearance tracks from all cameras.")

    patcher.stop()
    print("\n=====================================================")
    print("[SUCCESS] ALL CAMERA FILTERING SEARCH TESTS PASSED!")
    print("=====================================================\n")

if __name__ == "__main__":
    asyncio.run(run_tests())
