import asyncio
import sys
import os
import uuid
import tempfile
from unittest.mock import MagicMock

# Gracefully mock out heavy subpackages not needed for the API validation
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['insightface'] = MagicMock()
sys.modules['insightface.app'] = MagicMock()

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

# Enable testing isolated environments to trigger :memory: Qdrant client
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///:memory:"

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.main import app
from app.api import deps
from app.db.base_class import Base
from app.models.user import User
from app.models.student import Student, StudentPhoto, StudentFaceSession
from app.models.face_embedding import StudentFaceEmbedding
from app.models.video import Video
from app.models.track import Track
from app.models.incident import Incident, DetectedEvent, Evidence
from app.models.camera import Camera
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

async def test_complete_delete_system():
    # 1. Initialize Tables in memory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Instantiate Qdrant Store using the memory client
    qdrant_store = QdrantVectorStore()
    
    # ----------------------------------------------------
    # TEST 1: DELETE PHOTO
    # ----------------------------------------------------
    print("Executing Test 1: Upload and Delete Student Photo...")
    student_id = uuid.uuid4()
    photo_id = uuid.uuid4()
    
    temp_dir = tempfile.gettempdir()
    mock_photo_path = os.path.join(temp_dir, f"test_delete_photo_{uuid.uuid4().hex[:6]}.jpg")
    with open(mock_photo_path, "wb") as f:
        f.write(b"mock_photo_bytes")
        
    async with TestingSessionLocal() as db:
        # Create student
        student = Student(
            id=student_id,
            university_roll_number="UR20269991",
            name="Bob Smith",
            department="ECE",
            programme="B.Tech",
            year=1,
            semester=2,
            section="B",
            email="bob@ece.edu",
            embedding_generated=True
        )
        db.add(student)
        
        # Create photo
        photo = StudentPhoto(
            id=photo_id,
            student_id=student_id,
            photo_path=mock_photo_path,
            view="front",
            file_size=100,
            mime_type="image/jpeg",
            md5_hash="md5_hash_bob"
        )
        db.add(photo)
        
        # Create embedding record
        embedding = StudentFaceEmbedding(
            id=uuid.uuid4(),
            student_id=student_id,
            photo_id=photo_id,
            embedding=[0.5] * 512,
            quality_score=0.9,
            blur_score=100.0,
            pose_yaw=0.0,
            pose_pitch=0.0,
            pose_roll=0.0,
            face_bbox={"x1": 0, "y1": 0, "x2": 10, "y2": 10}
        )
        db.add(embedding)
        await db.commit()
        
    # Upsert face embedding in Qdrant
    qdrant_store.upsert_face_embedding(
        embedding_id=photo_id,
        vector=[0.5] * 512,
        payload={"student_id": student_id, "photo_id": photo_id}
    )
    
    # Assert physical file exists and Qdrant has point
    assert os.path.exists(mock_photo_path)
    res_points = qdrant_store.client.count(collection_name=qdrant_store.face_collection_name).count
    assert res_points == 1
    
    # Trigger DELETE endpoint
    response = client.delete(f"/api/v1/students/{student_id}/photos/{photo_id}")
    assert response.status_code == 204
    
    # Verify file deleted
    assert not os.path.exists(mock_photo_path)
    print("  Verified: Photo physical file deleted.")
    
    # Verify DB records deleted
    async with TestingSessionLocal() as db:
        photo_db = (await db.execute(select(StudentPhoto).filter(StudentPhoto.id == photo_id))).scalars().first()
        assert photo_db is None
        
        emb_db = (await db.execute(select(StudentFaceEmbedding).filter(StudentFaceEmbedding.photo_id == photo_id))).scalars().first()
        assert emb_db is None
        
        # Verify student.embedding_generated was updated to False
        student_db = (await db.execute(select(Student).filter(Student.id == student_id))).scalars().first()
        assert student_db.embedding_generated is False
        print("  Verified: Student db record updated to embedding_generated=False.")

    # Verify Qdrant points count is 0
    res_points = qdrant_store.client.count(collection_name=qdrant_store.face_collection_name).count
    assert res_points == 0
    print("  Verified: Qdrant face collection points count is 0.")
    print("[SUCCESS] Test 1 Passed.")

    # ----------------------------------------------------
    # TEST 2: DELETE CCTV VIDEO
    # ----------------------------------------------------
    print("\nExecuting Test 2: Upload and Delete CCTV Video...")
    video_id = uuid.uuid4()
    camera_id = uuid.uuid4()
    
    mock_video_path = os.path.join(temp_dir, f"test_delete_video_{uuid.uuid4().hex[:6]}.mp4")
    with open(mock_video_path, "wb") as f:
        f.write(b"mock_video_bytes")
        
    async with TestingSessionLocal() as db:
        # Create Camera
        camera = Camera(
            id=camera_id,
            name="Camera-1",
            building="Main Building",
            floor=1,
            location="Main Hall",
            direction="north",
            resolution="1920x1085"
        )
        db.add(camera)
        
        # Create Video
        video = Video(
            id=video_id,
            title="Surveillance Test Feed",
            filename=os.path.basename(mock_video_path),
            original_filename="cctv_test.mp4",
            file_path=mock_video_path,
            status="completed",
            uploaded_by=mock_user.id,
            camera_id=camera_id
        )
        db.add(video)
        await db.commit()
        
    # Seed mock Qdrant points for this video
    qdrant_store.client.upsert(
        collection_name=qdrant_store.collection_name,
        points=[
            qdrant_models.PointStruct(
                id=str(uuid.uuid4()),
                vector=[0.1] * 512,
                payload={"video_id": str(video_id), "camera_id": str(camera_id)}
            )
        ]
    )
    
    # Assert video file exists and Qdrant points count is 1
    assert os.path.exists(mock_video_path)
    res_cctv_points = qdrant_store.client.count(
        collection_name=qdrant_store.collection_name,
        count_filter=qdrant_models.Filter(
            must=[qdrant_models.FieldCondition(key="video_id", match=qdrant_models.MatchValue(value=str(video_id)))]
        )
    ).count
    assert res_cctv_points == 1
    
    # Trigger DELETE endpoint
    response = client.delete(f"/api/v1/videos/{video_id}")
    assert response.status_code == 204
    
    # Verify file deleted
    assert not os.path.exists(mock_video_path)
    print("  Verified: Video physical file deleted.")
    
    # Verify DB record deleted
    async with TestingSessionLocal() as db:
        video_db = (await db.execute(select(Video).filter(Video.id == video_id))).scalars().first()
        assert video_db is None
        print("  Verified: Video db record deleted.")
        
    # Verify Qdrant points for video are 0
    res_cctv_points = qdrant_store.client.count(
        collection_name=qdrant_store.collection_name,
        count_filter=qdrant_models.Filter(
            must=[qdrant_models.FieldCondition(key="video_id", match=qdrant_models.MatchValue(value=str(video_id)))]
        )
    ).count
    assert res_cctv_points == 0
    print("  Verified: Qdrant cctv collection points count for video is 0.")
    print("[SUCCESS] Test 2 Passed.")

    # ----------------------------------------------------
    # TEST 3: DELETE STUDENT RECORD
    # ----------------------------------------------------
    print("\nExecuting Test 3: Delete Student Record & Embeddings...")
    student_id_3 = uuid.uuid4()
    
    async with TestingSessionLocal() as db:
        student3 = Student(
            id=student_id_3,
            university_roll_number="UR20269993",
            name="Charlie Brown",
            department="CSE",
            programme="B.Tech",
            year=2,
            semester=4,
            section="A",
            email="charlie@cse.edu",
            embedding_generated=True
        )
        db.add(student3)
        await db.commit()
        
    # Seed face embedding in Qdrant
    qdrant_store.upsert_face_embedding(
        embedding_id=uuid.uuid4(),
        vector=[0.8] * 512,
        payload={"student_id": student_id_3}
    )
    
    # Assert Qdrant has point for student
    res_std_points = qdrant_store.client.count(
        collection_name=qdrant_store.face_collection_name,
        count_filter=qdrant_models.Filter(
            must=[qdrant_models.FieldCondition(key="student_id", match=qdrant_models.MatchValue(value=str(student_id_3)))]
        )
    ).count
    assert res_std_points == 1
    
    # Trigger DELETE endpoint
    response = client.delete(f"/api/v1/students/{student_id_3}")
    assert response.status_code == 204
    
    # Verify DB record deleted
    async with TestingSessionLocal() as db:
        student_db = (await db.execute(select(Student).filter(Student.id == student_id_3))).scalars().first()
        assert student_db is None
        print("  Verified: Student db record deleted.")
        
    # Verify Qdrant points for student are 0
    res_std_points = qdrant_store.client.count(
        collection_name=qdrant_store.face_collection_name,
        count_filter=qdrant_models.Filter(
            must=[qdrant_models.FieldCondition(key="student_id", match=qdrant_models.MatchValue(value=str(student_id_3)))]
        )
    ).count
    assert res_std_points == 0
    print("  Verified: Qdrant face collection points count for student is 0.")
    print("[SUCCESS] Test 3 Passed.")

    # ----------------------------------------------------
    # TEST 4: DELETE EVIDENCE FILE
    # ----------------------------------------------------
    print("\nExecuting Test 4: Delete Forensic Evidence...")
    incident_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    
    mock_evidence_path = os.path.join(temp_dir, f"test_delete_evidence_{uuid.uuid4().hex[:6]}.jpg")
    with open(mock_evidence_path, "wb") as f:
        f.write(b"mock_evidence_bytes")
        
    async with TestingSessionLocal() as db:
        # Create Incident
        incident = Incident(
            id=incident_id,
            incident_type="Boundary Crossing",
            camera_id=camera_id,
            confidence=0.9,
            explanation="Test incident"
        )
        db.add(incident)
        
        # Create Evidence record
        evidence = Evidence(
            id=evidence_id,
            incident_id=incident_id,
            evidence_type="screenshot",
            file_path=mock_evidence_path
        )
        db.add(evidence)
        await db.commit()
        
    # Assert physical file exists and DB record exists
    assert os.path.exists(mock_evidence_path)
    
    # Trigger DELETE endpoint
    response = client.delete(f"/api/v1/evidence/{evidence_id}")
    assert response.status_code == 204
    
    # Verify file deleted
    assert not os.path.exists(mock_evidence_path)
    print("  Verified: Evidence physical file deleted.")
    
    # Verify DB record deleted
    async with TestingSessionLocal() as db:
        evidence_db = (await db.execute(select(Evidence).filter(Evidence.id == evidence_id))).scalars().first()
        assert evidence_db is None
        print("  Verified: Evidence db record deleted.")
    print("[SUCCESS] Test 4 Passed.")

    print("\n=======================================================")
    print("[SUCCESS] ALL COMPLETE DELETION SYSTEM TESTS PASSED!")
    print("=======================================================\n")

if __name__ == "__main__":
    asyncio.run(test_complete_delete_system())
