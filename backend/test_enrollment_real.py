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
from app.services.vector_store import QdrantVectorStore

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

async def test_face_enrollment_indexing_pipeline():
    # 1. Initialize Tables in memory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Make sure Qdrant collections exist in the memory client
    qdrant_store = QdrantVectorStore()
    
    # Pre-check Qdrant face collection points
    coll_info = qdrant_store.client.get_collection(qdrant_store.face_collection_name)
    assert coll_info.points_count == 0

    student_id = uuid.uuid4()
    
    # 2. Create student database record
    async with TestingSessionLocal() as db:
        new_student = Student(
            id=student_id,
            university_roll_number="UR20260718",
            name="Alice Cooper",
            department="CSE",
            programme="B.Tech",
            year=3,
            semester=6,
            section="A",
            email="alice@smartcampus.com",
            embedding_generated=False
        )
        db.add(new_student)
        
        session = StudentFaceSession(
            id=uuid.uuid4(),
            student_id=student_id,
            status="pending"
        )
        db.add(session)
        await db.commit()

    # 3. Simulate photo upload on disk
    temp_dir = tempfile.gettempdir()
    mock_photo_path = os.path.join(temp_dir, f"test_enroll_photo_{uuid.uuid4().hex[:6]}.jpg")
    
    # Create simple dummy image bytes
    import cv2
    import numpy as np
    dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.imwrite(mock_photo_path, dummy_img)

    try:
        # Create photo record manually linked
        async with TestingSessionLocal() as db:
            photo = StudentPhoto(
                id=uuid.uuid4(),
                student_id=student_id,
                photo_path=mock_photo_path,
                view="front",
                file_size=1024,
                mime_type="image/jpeg",
                md5_hash="md5hash123",
                metadata_json={"original_filename": "test.jpg"}
            )
            db.add(photo)
            await db.commit()

        # 4. Trigger Face Enrollment API call with patched face processor
        print("Triggering Face Enrollment for student Alice Cooper...")
        
        mock_engine_res = {
            "success": True,
            "embedding": [0.1] * 512,
            "quality_score": 0.95,
            "blur_score": 120.0,
            "pose": (0.0, 0.0, 0.0),
            "bbox": [10.0, 10.0, 100.0, 100.0]
        }
        
        from unittest.mock import patch
        with patch("app.pipeline.face_engine.FaceEnrollmentEngine.process_photo", return_value=mock_engine_res):
            response = client.post(f"/api/v1/students/{student_id}/enroll")
            assert response.status_code == 200
            data = response.json()
            print("Enrollment API response data:", data)
            assert data["successful"] == 1
            assert data["failed"] == 0

        # 5. Verify Student DB updates (embedding_generated=True)
        async with TestingSessionLocal() as db:
            std_stmt = select(Student).filter(Student.id == student_id)
            std_res = await db.execute(std_stmt)
            student = std_res.scalars().first()
            assert student.embedding_generated is True
            print("Verified: Student.embedding_generated is True.")

            # Verify StudentFaceEmbedding count
            emb_stmt = select(StudentFaceEmbedding).filter(StudentFaceEmbedding.student_id == student_id)
            emb_res = await db.execute(emb_stmt)
            embeddings = emb_res.scalars().all()
            assert len(embeddings) == 1
            print("Verified: StudentFaceEmbedding count in DB is 1.")

        # 6. Verify Qdrant points count increases by 1
        coll_info = qdrant_store.client.get_collection(qdrant_store.face_collection_name)
        print("Qdrant collection face points count:", coll_info.points_count)
        assert coll_info.points_count == 1
        print("Verified: Qdrant face collection points count increases to 1.")

        print("\n================================================")
        print("[SUCCESS] FACE ENROLLMENT INTEGRATION TEST PASSED!")
        print("================================================\n")

    finally:
        if os.path.exists(mock_photo_path):
            os.remove(mock_photo_path)

if __name__ == "__main__":
    asyncio.run(test_face_enrollment_indexing_pipeline())
