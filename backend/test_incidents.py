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

# Add backend to sys.path
backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.main import app
from app.api import deps
from app.db.base_class import Base
from app.models.user import User
from app.models.camera import Camera
from app.models.student import Student
from app.models.incident import Incident, IncidentPerson, Evidence, DetectedEvent

# In-memory test engine
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

async def test_incident_query_engine():
    # 1. Initialize Tables in memory
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with TestingSessionLocal() as db:
        # 2. Add Test Camera
        camera_id = uuid.uuid4()
        camera = Camera(
            id=camera_id,
            name="Camera-NorthGate",
            building="Admin Block",
            floor=1,
            location="North Entrance Gate",
            direction="North",
            resolution="1920x1080",
            status="active"
        )
        db.add(camera)

        # 3. Add Test Student
        student_id = uuid.uuid4()
        student = Student(
            id=student_id,
            university_roll_number="CS22B045",
            name="Deepu Bijoy",
            department="CSE",
            programme="S8 CSE A",
            year=4,
            semester=8,
            section="A",
            email="deepu@smartcampus.com",
            status="active"
        )
        db.add(student)

        # 4. Add Test Incident
        incident_id = uuid.uuid4()
        incident = Incident(
            id=incident_id,
            incident_type="Boundary Crossing",
            timestamp=datetime.now(timezone.utc),
            camera_id=camera_id,
            confidence=0.98,
            explanation="Deepu Bijoy crossed boundary line 'North Gate Fence' on Camera-NorthGate."
        )
        db.add(incident)

        # 5. Link Student to Incident
        inc_person = IncidentPerson(
            id=uuid.uuid4(),
            incident_id=incident_id,
            student_id=student_id,
            confidence=0.95
        )
        db.add(inc_person)

        # 6. Add Evidence Files
        ev_screenshot = Evidence(
            id=uuid.uuid4(),
            incident_id=incident_id,
            evidence_type="screenshot",
            file_path="storage/crops/track_1_frame_50.jpg",
            timestamp=datetime.now(timezone.utc)
        )
        ev_video = Evidence(
            id=uuid.uuid4(),
            incident_id=incident_id,
            evidence_type="video",
            file_path="storage/evidence/clip_crossing.mp4",
            timestamp=datetime.now(timezone.utc)
        )
        db.add(ev_screenshot)
        db.add(ev_video)

        await db.commit()

    # 7. Query endpoint using TestClient
    print("Verifying POST /api/v1/investigations/query with boundary wall crossing query...")
    response = client.post("/api/v1/investigations/query", json={
        "query": "Who jumped the wall?"
    })
    
    assert response.status_code == 200
    res_json = response.json()
    assert "results" in res_json
    results = res_json["results"]
    assert len(results) == 1
    
    result = results[0]
    assert result["incident_type"] == "Boundary Crossing"
    assert result["camera_name"] == "Camera-NorthGate"
    assert result["screenshot_evidence"] == "/storage/crops/track_1_frame_50.jpg"
    assert result["video_evidence"] == "/storage/evidence/clip_crossing.mp4"
    assert len(result["students_involved"]) == 1
    
    student_info = result["students_involved"][0]
    assert student_info["name"] == "Deepu Bijoy"
    assert student_info["roll_number"] == "CS22B045"
    assert student_info["class_name"] == "S8 CSE A A"  # programme + section

    print("POST /api/v1/investigations/query test PASSED successfully!")

if __name__ == "__main__":
    asyncio.run(test_incident_query_engine())
