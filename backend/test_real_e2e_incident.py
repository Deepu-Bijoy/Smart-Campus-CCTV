import asyncio
import os
import sys
import uuid
import time
import io
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Set fallback environment flags before imports
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_incident_e2e.db"

# Mock out heavy deep learning models and client libraries
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['insightface'] = MagicMock()
sys.modules['insightface.app'] = MagicMock()

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from sqlalchemy import select
from fastapi.testclient import TestClient
from fastapi import status
from app.main import app
from app.api import deps
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.models.user import User
from app.models.student import Student
from app.models.track import Track
from app.models.recognition import StudentRecognitionEvent
from app.models.camera import Camera, VirtualZone
from app.models.video import Video
from app.models.incident import Incident, IncidentPerson, Evidence, DetectedEvent
from app.services.vector_store import QdrantVectorStore

client = TestClient(app)

async def init_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

def run_e2e_test():
    print("=== Start Real End-to-End Incident Integration Test ===")
    asyncio.run(init_test_db())

    # 1. Setup Auth Operator user
    mock_operator_id = uuid.uuid4()
    mock_operator = User(
        id=mock_operator_id,
        email="operator@smartcampus.com",
        hashed_password="hashedpassword123",
        full_name="Lead Security Operator",
        is_active=True
    )
    app.dependency_overrides[deps.get_current_user] = lambda: mock_operator

    async def get_test_db():
        async with SessionLocal() as session:
            yield session
    app.dependency_overrides[deps.get_db] = get_test_db

    # 2. Register Student & Create Face Embedding
    student_id = uuid.uuid4()
    print("Step 1: Enrolling Test Student...")
    async def populate_registry():
        async with SessionLocal() as db:
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
            await db.commit()
            
            # Sync face embedding to Qdrant test collection
            qdrant_store = QdrantVectorStore()
            qdrant_store.upsert_face_embedding(
                embedding_id=uuid.uuid4(),
                vector=[0.1] * 512,
                payload={
                    "student_id": str(student_id),
                    "photo_id": str(uuid.uuid4()),
                    "quality": 0.95
                }
            )
    asyncio.run(populate_registry())
    print("Student Deepu Bijoy enrolled.")

    # 3. Create Camera & Define Fence Boundary Zone
    camera_id = uuid.uuid4()
    print("Step 2: Configuring Camera and Virtual Fence Zone...")
    async def populate_camera_zones():
        async with SessionLocal() as db:
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
            await db.commit()
            
            # Define virtual fence zone coordinates crossing y = 150
            zone = VirtualZone(
                id=uuid.uuid4(),
                camera_id=camera_id,
                name="Fence-North",
                zone_type="Fence",
                geometry_type="line",
                coordinates="[[0, 150], [1000, 150]]" # line segment crossing y=150
            )
            db.add(zone)
            await db.commit()
    asyncio.run(populate_camera_zones())
    print("Camera-GateA configured with 'Fence-North' line zone.")

    # 5. Run Video Ingestion Pipeline (mocking heavy Vision frames processing output)
    print("Step 4: Simulating FrameProcessor extraction outputs...")
    mock_tracks = [
        {"tracker_id": 1, "object_class": "person", "start_time": 0.0, "end_time": 10.0, "temp_id": 1}
    ]
    # Trajectory goes from y=10 to y=300, crossing the fence zone line at y=150
    mock_detections = [
        {"frame_number": 0, "timestamp_seconds": 0.0, "bounding_box": [10.0, 10.0, 100.0, 100.0], "confidence": 0.9, "track_temp_id": 1, "object_class": "person"},
        {"frame_number": 50, "timestamp_seconds": 10.0, "bounding_box": [200.0, 300.0, 300.0, 400.0], "confidence": 0.9, "track_temp_id": 1, "object_class": "person"}
    ]
    mock_reids = [
        {"track_temp_id": 1, "embedding": [0.1]*512, "timestamp_seconds": 5.0, "crop_path": "storage/crops/test_crop.jpg", "camera_id": "Camera-GateA"}
    ]
    mock_clips = [
        {"track_temp_id": 1, "embedding": [0.2]*512, "timestamp_seconds": 5.0, "crop_path": "storage/crops/test_crop.jpg", "object_class": "person", "confidence": 0.9, "camera_id": "Camera-GateA"}
    ]

    # Patch FrameProcessor.process, StudentIdentifier, and generate_subclip
    with patch("app.pipeline.orchestrator.FrameProcessor.process", return_value=(mock_tracks, mock_detections, mock_reids, mock_clips, 100)), \
         patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop", return_value={"success": True, "student_id": student_id, "similarity_score": 0.85, "confidence": "high"}), \
         patch("app.event_engine.event_engine.generate_subclip", return_value=True) as mock_clip_gen:

        # 4. Upload CCTV Footage associated with Camera-GateA (with active mocks!)
        print("Step 3: Uploading Video mapped to Camera-GateA...")
        video_content = b"fake video bytes representing mp4"
        file_payload = ("cctv_footage.mp4", io.BytesIO(video_content), "video/mp4")
        
        # Check that upload route accepts camera_id parameter
        response = client.post(
            "/api/v1/videos/upload", 
            data={"title": "Boundary crossing incident feed", "camera_id": str(camera_id)},
            files={"file": file_payload}
        )
        assert response.status_code == status.HTTP_201_CREATED, f"Upload failed: {response.text}"
        video_data = response.json()
        video_id = uuid.UUID(video_data["id"])
        print(f"Video uploaded. Video ID: {video_id}, Associated Camera ID: {video_data.get('camera_id')}")
        assert uuid.UUID(video_data["camera_id"]) == camera_id
        
        print("Waiting for eager Celery processor...")

    # 6. Verify Database Persistence of Incident and Evidence
    print("Step 5: Verifying Database Persistence & Relations...")
    async def verify_records():
        async with SessionLocal() as db:
            # Query Incidents
            inc_stmt = select(Incident)
            inc_res = await db.execute(inc_stmt)
            incidents = inc_res.scalars().all()
            print(f"Total Incidents created: {len(incidents)}")
            assert len(incidents) > 0, "Incident was not created by event engine!"
            
            incident = incidents[0]
            print(f"Incident Type: {incident.incident_type}")
            assert incident.incident_type == "Boundary Crossing"
            print(f"Incident Explanation: {incident.explanation}")
            
            # Query IncidentPersons
            ip_stmt = select(IncidentPerson).filter(IncidentPerson.incident_id == incident.id)
            ip_res = await db.execute(ip_stmt)
            persons = ip_res.scalars().all()
            print(f"IncidentPersons count: {len(persons)}")
            assert len(persons) == 1
            assert persons[0].student_id == student_id
            
            # Query Evidence
            ev_stmt = select(Evidence).filter(Evidence.incident_id == incident.id)
            ev_res = await db.execute(ev_stmt)
            evidences = ev_res.scalars().all()
            print(f"Evidence files mapped: {len(evidences)}")
            assert len(evidences) == 2
            evidence_types = [ev.evidence_type for ev in evidences]
            assert "screenshot" in evidence_types
            assert "video" in evidence_types

    asyncio.run(verify_records())

    # 7. Query NLP Assistant Endpoint
    print("Step 6: Executing Natural Language Investigation Query requests...")
    query_cases = [
        "Did anyone cross the boundary wall?",
        "Did anyone jump over the boundary wall?",
        "Who crossed the boundary?",
        "Was there any unauthorized boundary crossing?"
    ]
    
    for q in query_cases:
        response = client.post("/api/v1/investigations/query", json={"query": q})
        assert response.status_code == 200
        res_data = response.json()
        assert "results" in res_data
        results = res_data["results"]
        assert len(results) == 1
        
        item = results[0]
        assert item["incident_type"] == "Boundary Crossing"
        assert item["severity"] == "High"
        assert item["camera"]["name"] == "Camera-GateA"
        assert item["person"]["identity_status"] == "Identified"
        assert item["person"]["name"] == "Deepu Bijoy"
        assert item["person"]["roll_number"] == "CS22B045"
        assert item["confidence"]["event_confidence"] == 0.98
        print(f"Query '{q}' routed to Boundary Crossing successfully.")

    # 7.5 Compile Hardened Evaluation metrics for research
    print("Step 6.5: Compiling Hardened Evaluation metrics...")
    from app.evaluation.eval_framework import generate_evaluation_metrics, write_reports
    rep = generate_evaluation_metrics()
    write_reports(rep, "./storage/evaluation")
    
    assert os.path.exists("./storage/evaluation/evaluation_report.json")
    assert os.path.exists("./storage/evaluation/evaluation_report.md")
    print("Evaluation report files successfully written and verified.")

    # 8. Print counts for Phase 7 report
    async def get_db_counts():
        async with SessionLocal() as db:
            from sqlalchemy import func
            counts = {}
            for model, name in [
                (Student, "students"),
                (Video, "videos"),
                (Track, "tracks"),
                (StudentRecognitionEvent, "student_recognition_events"),
                (DetectedEvent, "detected_events"),
                (Incident, "incidents"),
                (IncidentPerson, "incident_persons"),
                (Evidence, "evidence")
            ]:
                res = await db.execute(select(func.count(model.id)))
                counts[name] = res.scalar() or 0
            return counts

    db_counts = asyncio.run(get_db_counts())
    print("\nDatabase Counts post E2E execution:")
    for k, v in db_counts.items():
        print(f"  {k}: {v}")

    # Clean up test database file
    try:
        db_file = "./storage/test_incident_e2e.db"
        if os.path.exists(db_file):
            os.remove(db_file)
            print("Cleaned up isolated test database file successfully.")
    except Exception as e:
        print(f"Warning: failed to remove test database: {str(e)}")

    print("\n==============================================")
    print("[SUCCESS] ALL END-TO-END VERIFICATIONS PASSED!")
    print("==============================================\n")

if __name__ == "__main__":
    run_e2e_test()
