import asyncio
import os
import sys
import uuid
import io
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Set fallback environment flags before imports
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_violence_feature.db"

# Mock out heavy deep learning models before backend imports
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
from app.models.student import Student, StudentPhoto
from app.models.camera import Camera
from app.models.video import Video
from app.models.incident import Incident, IncidentPerson, Evidence, DetectedEvent
from app.models.report import Report

client = TestClient(app)

async def init_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

def test_violence_detection_workflow():
    print("\n=== START TEST: Dedicated Violence Detection Workflow ===")
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

    # 2. Setup Camera, Enrolled Student and StudentPhoto
    student_id = uuid.uuid4()
    camera_id = uuid.uuid4()

    async def setup_test_entities():
        async with SessionLocal() as db:
            camera = Camera(
                id=camera_id,
                name="Cafeteria Courtyard Camera",
                building="Student Center",
                floor=1,
                location="Courtyard Area",
                direction="South",
                resolution="1920x1080",
                status="active"
            )
            db.add(camera)

            student = Student(
                id=student_id,
                university_roll_number="CS22B099",
                name="Vikramaditya Roy",
                department="Computer Science",
                programme="B.Tech CSE",
                year=3,
                semester=6,
                section="A",
                email="vikram@smartcampus.com",
                status="active"
            )
            db.add(student)

            photo = StudentPhoto(
                id=uuid.uuid4(),
                student_id=student_id,
                photo_path="storage/students/test_vikram_front.jpg",
                view="front",
                file_size=10240,
                mime_type="image/jpeg",
                md5_hash="fakehash123456"
            )
            db.add(photo)

            await db.commit()

    asyncio.run(setup_test_entities())
    print("Test camera, student and profile photo created.")

    # 3. Simulate Video Ingestion & Vision outputs
    mock_tracks = [
        {"tracker_id": 101, "object_class": "person", "start_time": 0.0, "end_time": 10.0, "temp_id": 101},
        {"tracker_id": 102, "object_class": "person", "start_time": 0.0, "end_time": 10.0, "temp_id": 102}
    ]
    mock_detections = [
        {"frame_number": 0, "timestamp_seconds": 0.0, "bounding_box": [50.0, 50.0, 150.0, 200.0], "confidence": 0.95, "track_temp_id": 101, "object_class": "person"},
        {"frame_number": 25, "timestamp_seconds": 5.0, "bounding_box": [120.0, 60.0, 220.0, 210.0], "confidence": 0.92, "track_temp_id": 102, "object_class": "person"}
    ]
    mock_reids = [
        {"track_temp_id": 101, "embedding": [0.1] * 512, "timestamp_seconds": 5.0, "crop_path": "storage/crops/vikram_crop.jpg", "camera_id": str(camera_id)}
    ]
    mock_clips = [
        {"track_temp_id": 101, "embedding": [0.2] * 512, "timestamp_seconds": 5.0, "crop_path": "storage/crops/vikram_crop.jpg", "object_class": "person", "confidence": 0.9, "camera_id": str(camera_id)}
    ]

    # Patch FrameProcessor, StudentIdentifier, and EventDetectionEngine
    with patch("app.api.v1.violence.FrameProcessor.process", return_value=(mock_tracks, mock_detections, mock_reids, mock_clips, 50)), \
         patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop", return_value={"success": True, "student_id": student_id, "similarity_score": 0.88, "confidence": "high"}), \
         patch("app.api.v1.violence.generate_subclip", return_value=True):

        print("Testing POST /api/v1/violence/analyze with video file...")
        fake_video_bytes = b"fake video content for violence test"
        file_payload = ("fight_scene_cctv.mp4", io.BytesIO(fake_video_bytes), "video/mp4")

        response = client.post(
            "/api/v1/violence/analyze",
            data={
                "title": "Courtyard Brawl Analysis",
                "camera_id": str(camera_id)
            },
            files={"file": file_payload}
        )

        assert response.status_code == status.HTTP_200_OK, f"Analysis failed: {response.text}"
        data = response.json()
        print(f"Status returned: {data.get('status')}")
        print(f"Verdict: {data.get('verdict')}")
        print(f"Total Segments: {data.get('total_segments')}")

        assert "status" in data
        assert "verdict" in data
        assert "identified_students" in data
        assert data["video_title"] == "Courtyard Brawl Analysis"

        # 4. Inject a test Incident to verify full segment formatting & report generation
        incident_id = uuid.uuid4()
        async def inject_violence_incident(vid_id):
            async with SessionLocal() as db:
                inc = Incident(
                    id=incident_id,
                    incident_type="Fight",
                    timestamp=datetime.now(timezone.utc),
                    camera_id=camera_id,
                    confidence=0.88,
                    explanation="Detected physical fight/altercation at 5.0s on camera Cafeteria Courtyard Camera. Multi-signal breakdown: Motion dynamics: 0.92, Interaction proximity: 0.88, CLIP score: 0.74."
                )
                db.add(inc)

                det_evt = DetectedEvent(
                    id=uuid.uuid4(),
                    incident_id=incident_id,
                    event_type="FIGHT",
                    camera_id=camera_id,
                    video_id=uuid.UUID(vid_id),
                    timestamp=datetime.now(timezone.utc),
                    confidence=0.88
                )
                db.add(det_evt)

                inc_person = IncidentPerson(
                    id=uuid.uuid4(),
                    incident_id=incident_id,
                    student_id=student_id,
                    confidence=0.88
                )
                db.add(inc_person)

                ev_screen = Evidence(
                    id=uuid.uuid4(),
                    incident_id=incident_id,
                    evidence_type="screenshot",
                    file_path="storage/crops/evidence_screenshot.jpg",
                    timestamp=datetime.now(timezone.utc)
                )
                db.add(ev_screen)

                ev_video = Evidence(
                    id=uuid.uuid4(),
                    incident_id=incident_id,
                    evidence_type="video",
                    file_path=f"storage/evidence/clip_{incident_id.hex}.mp4",
                    timestamp=datetime.now(timezone.utc)
                )
                db.add(ev_video)

                await db.commit()

        video_id_str = data["video_id"]
        asyncio.run(inject_violence_incident(video_id_str))

        # Re-query analysis with existing video_id
        re_response = client.post(
            "/api/v1/violence/analyze",
            data={
                "video_id": video_id_str,
                "camera_id": str(camera_id)
            }
        )
        assert re_response.status_code == status.HTTP_200_OK
        re_data = re_response.json()

        assert re_data["status"] == "VIOLENCE_DETECTED"
        assert re_data["total_segments"] >= 1
        assert len(re_data["identified_students"]) >= 1

        student_card = re_data["identified_students"][0]
        assert student_card["name"] == "Vikramaditya Roy"
        assert student_card["roll_number"] == "CS22B099"
        assert student_card["profile_photo_url"] is not None

        segment = re_data["segments"][0]
        assert segment["confidence"] >= 0.80
        assert segment["breakdown"]["motion_dynamics"] > 0
        assert segment["breakdown"]["person_interaction"] > 0
        assert segment["breakdown"]["clip_similarity"] > 0
        print(f"Identified student in violence event: {student_card['name']} (Roll: {student_card['roll_number']})")
        print(f"Multi-signal breakdown: Motion={segment['breakdown']['motion_dynamics']}, Proximity={segment['breakdown']['person_interaction']}, CLIP={segment['breakdown']['clip_similarity']}")

        # 5. Test GET /api/v1/violence/history
        print("Testing GET /api/v1/violence/history...")
        hist_response = client.get("/api/v1/violence/history")
        assert hist_response.status_code == status.HTTP_200_OK
        history_items = hist_response.json()
        assert len(history_items) >= 1
        assert "Vikramaditya Roy" in history_items[0]["students"]
        print(f"Violence history returned {len(history_items)} recorded incidents.")

        # 6. Test POST /api/v1/violence/report (generate report)
        print("Testing POST /api/v1/violence/report...")
        rep_response = client.post(
            "/api/v1/violence/report",
            json={
                "incident_id": str(incident_id),
                "title": "Official Violence Investigation Report - Cafeteria Courtyard",
                "additional_notes": "Immediate security intervention logged."
            }
        )
        assert rep_response.status_code == status.HTTP_201_CREATED
        rep_data = rep_response.json()
        assert rep_data["success"] is True
        assert "report_id" in rep_data
        print(f"Forensic Report generated successfully. Report ID: {rep_data['report_id']}")

        # 7. Test Backward Compatibility: Verify GET /api/v1/events continues to function
        print("Verifying backward compatibility: GET /api/v1/events/...")
        evt_res = client.get("/api/v1/events/")
        assert evt_res.status_code == status.HTTP_200_OK
        evts = evt_res.json()
        assert len(evts) >= 1
        assert any(e["event_type"] == "FIGHT" for e in evts)
        print("Backward compatibility verified: Security Alerts log correctly includes FIGHT events.")

    print("=== VIOLENCE DETECTION WORKFLOW INTEGRATION TEST PASSED ===\n")

if __name__ == "__main__":
    test_violence_detection_workflow()
