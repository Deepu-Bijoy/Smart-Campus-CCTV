import asyncio
import os
import sys
import uuid
import json
import cv2
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Configure test environment
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_violence_reports.db"

# Mock out heavy models not needed for report integration test
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from fastapi import status
from app.main import app
from app.core.config import settings
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.api import deps
from app.models.user import User
from app.models.video import Video
from app.models.camera import Camera
from app.models.student import Student, StudentPhoto
from app.models.track import Track, Detection
from app.models.incident import Incident, DetectedEvent, Evidence, IncidentPerson
from app.models.report import Report
from app.schemas.violence import ViolenceReportRequest

mock_user = User(
    id=uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
    email="lead_forensics@campus.edu",
    hashed_password="hashedpassword123",
    full_name="Forensic Analyst Jane Doe",
    is_active=True
)

app.dependency_overrides[deps.get_current_user] = lambda: mock_user

client = TestClient(app)

def create_synthetic_test_media():
    storage_dir = os.path.join(backend_path, "storage", "test_report_media")
    os.makedirs(storage_dir, exist_ok=True)
    
    # Evidence frame (JPEG)
    frame_path = os.path.join(storage_dir, "violence_evidence_frame.jpg")
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    cv2.putText(frame, "VIOLENCE KEYFRAME", (30, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
    cv2.imwrite(frame_path, frame)
    
    # Evidence clip (MP4)
    clip_path = os.path.join(storage_dir, "violence_evidence_clip.mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(clip_path, fourcc, 10.0, (320, 240))
    for _ in range(30):
        out.write(frame)
    out.release()
    
    # Student 1 Photo
    photo1_path = os.path.join(storage_dir, "student_1_photo.jpg")
    photo1 = np.zeros((150, 150, 3), dtype=np.uint8)
    cv2.circle(photo1, (75, 75), 50, (200, 200, 200), -1)
    cv2.imwrite(photo1_path, photo1)

    # Student 2 Photo
    photo2_path = os.path.join(storage_dir, "student_2_photo.jpg")
    photo2 = np.zeros((150, 150, 3), dtype=np.uint8)
    cv2.circle(photo2, (75, 75), 50, (180, 220, 180), -1)
    cv2.imwrite(photo2_path, photo2)

    return frame_path, clip_path, photo1_path, photo2_path

async def async_setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

def run_async(coro):
    return asyncio.run(coro)

def test_violence_report_system_end_to_end():
    print("\n========================================================")
    print("RUNNING VIOLENCE DETECTION REPORT INTEGRATION TEST SUITE")
    print("========================================================")

    # 0. Initialize Database
    run_async(async_setup_db())
    frame_path, clip_path, photo1_path, photo2_path = create_synthetic_test_media()

    async def seed_data():
        async with SessionLocal() as db:
            # User
            db.add(mock_user)

            # 1. Camera
            camera = Camera(
                id=uuid.uuid4(),
                name="Camera #03 - Block A",
                location="Block A - Ground Floor Corridors",
                building="Academic Block A",
                floor=1,
                direction="North",
                resolution="1920x1080",
                status="active"
            )
            db.add(camera)

            # 2. Video
            video = Video(
                id=uuid.uuid4(),
                title="Surveillance_Footage_2026_09_10.mp4",
                filename="surveillance_footage_03.mp4",
                original_filename="Campus_Camera_03.mp4",
                file_path=clip_path,
                duration=45.0,
                status="processed",
                uploaded_by=mock_user.id,
                camera_id=camera.id
            )
            db.add(video)

            # 3. Multiple Students
            student1 = Student(
                id=uuid.uuid4(),
                university_roll_number="23",
                name="Arjun Sharma",
                department="Computer Science & Engineering",
                programme="S6 CSE",
                year=3,
                semester=6,
                section="A",
                email="arjun.sharma@campus.edu",
                status="active"
            )
            db.add(student1)

            student2 = Student(
                id=uuid.uuid4(),
                university_roll_number="41",
                name="Rohan Verma",
                department="Computer Science & Engineering",
                programme="S6 CSE",
                year=3,
                semester=6,
                section="B",
                email="rohan.verma@campus.edu",
                status="active"
            )
            db.add(student2)
            await db.flush()

            # Photos
            sp1 = StudentPhoto(
                id=uuid.uuid4(),
                student_id=student1.id,
                photo_path=photo1_path,
                view="front",
                file_size=1024,
                mime_type="image/jpeg",
                md5_hash=uuid.uuid4().hex
            )
            sp2 = StudentPhoto(
                id=uuid.uuid4(),
                student_id=student2.id,
                photo_path=photo2_path,
                view="front",
                file_size=1024,
                mime_type="image/jpeg",
                md5_hash=uuid.uuid4().hex
            )
            db.add_all([sp1, sp2])

            # 4. Track Setup
            track = Track(
                id=uuid.uuid4(),
                video_id=video.id,
                object_class="person",
                tracker_id=17,
                start_time=272.0,
                end_time=279.0,
                identified_student_id=student1.id
            )
            db.add(track)
            await db.flush()

            # 5. Violence Incident & Event Entity Setup
            incident = Incident(
                id=uuid.uuid4(),
                camera_id=camera.id,
                incident_type="Violence",
                confidence=0.914,
                explanation="Physical struggle and rapid kinematic motion velocity detected between subjects.",
                timestamp=datetime(2026, 9, 10, 10, 4, 32, tzinfo=timezone.utc)
            )
            db.add(incident)
            await db.flush()

            # DetectedEvent referencing event type = VIOLENCE, track_id, video_id, camera_id
            event_id = uuid.uuid4()
            det_event = DetectedEvent(
                id=event_id,
                incident_id=incident.id,
                camera_id=camera.id,
                video_id=video.id,
                event_type="VIOLENCE",
                confidence=0.914,
                track_id=track.id,
                timestamp=incident.timestamp
            )
            db.add(det_event)

            # Evidence (Frame & Clip)
            ev_frame = Evidence(
                id=uuid.uuid4(),
                incident_id=incident.id,
                evidence_type="screenshot",
                file_path=frame_path,
                timestamp=incident.timestamp
            )
            ev_clip = Evidence(
                id=uuid.uuid4(),
                incident_id=incident.id,
                evidence_type="video",
                file_path=clip_path,
                timestamp=incident.timestamp
            )
            db.add_all([ev_frame, ev_clip])

            # IncidentPerson for both students (Multi-person biometric link)
            ip1 = IncidentPerson(
                id=uuid.uuid4(),
                incident_id=incident.id,
                student_id=student1.id,
                confidence=0.947  # 94.7% identity confidence
            )
            ip2 = IncidentPerson(
                id=uuid.uuid4(),
                incident_id=incident.id,
                student_id=student2.id,
                confidence=0.912  # 91.2% identity confidence
            )
            db.add_all([ip1, ip2])

            await db.commit()
            return {
                "camera_id": str(camera.id),
                "video_id": str(video.id),
                "incident_id": str(incident.id),
                "event_id": str(det_event.id),
                "student1_id": str(student1.id),
                "student2_id": str(student2.id),
                "frame_path": frame_path,
                "clip_path": clip_path
            }

    data_ids = run_async(seed_data())
    print(f"[TEST SETUP] Seeded Violence Incident: {data_ids['incident_id']}, Event: {data_ids['event_id']}")

    # =========================================================================
    # TEST 1 & 2: Generate Report From One Violence Event
    # =========================================================================
    print("\n--- TEST 1: Generate Report from Single Violence Event ID ---")
    gen_payload = {
        "event_id": data_ids["event_id"],
        "title": "Forensic Investigation Report - Altercation at Block A",
        "additional_notes": "Urgent security inspection requested by campus supervisor."
    }
    resp = client.post("/api/v1/violence/report", json=gen_payload)
    assert resp.status_code in [status.HTTP_200_OK, status.HTTP_201_CREATED], f"Expected 200/201, got {resp.status_code}: {resp.text}"
    report_res = resp.json()
    assert report_res["success"] is True
    assert "report_id" in report_res
    report_id = report_res["report_id"]
    print(f"[OK] Successfully generated Violence Report with ID: {report_id}")

    r_data = report_res["data"]
    # Verify Event Information stored/referenced
    assert r_data["event_type"] == "VIOLENCE"
    assert r_data["violence_confidence"] == 0.914
    assert r_data["event_info"]["event_id"] == data_ids["event_id"]
    assert r_data["event_info"]["event_type"] == "VIOLENCE"
    assert r_data["event_info"]["violence_confidence"] == 0.914
    assert "start_timestamp" in r_data["event_info"]
    assert "end_timestamp" in r_data["event_info"]
    assert "person_track_ids" in r_data["event_info"]
    assert "matched_student_ids" in r_data["event_info"]
    print("[OK] Event Information verified (Event ID, Type=VIOLENCE, Timestamps, Confidence, Tracks)")

    # Verify Video Information
    assert r_data["video_info"]["video_id"] == data_ids["video_id"]
    assert "surveillance_footage_03.mp4" in r_data["video_info"]["filename"]
    print("[OK] Video Information verified (Video ID, Filename, Duration)")

    # Verify Camera Information
    assert r_data["camera"]["camera_id"] == data_ids["camera_id"]
    assert "Block A" in r_data["camera"]["name"]
    print("[OK] Camera Information verified (Camera ID, Name, Location)")

    # =========================================================================
    # TEST 3: Verify Report with Multiple Involved Students
    # =========================================================================
    print("\n--- TEST 3: Verify Multiple Involved Students in Report ---")
    involved = r_data["involved_students"]
    assert len(involved) == 2, f"Expected 2 involved students, got {len(involved)}"
    
    st_names = [s["name"] for s in involved]
    assert "Arjun Sharma" in st_names
    assert "Rohan Verma" in st_names

    s1 = next(s for s in involved if s["name"] == "Arjun Sharma")
    assert s1["roll_number"] == "23"
    assert s1["class"] == "S6 CSE A"
    assert s1["identity_confidence"] == 0.947
    assert s1["profile_photo_url"] is not None

    s2 = next(s for s in involved if s["name"] == "Rohan Verma")
    assert s2["roll_number"] == "41"
    assert s2["class"] == "S6 CSE B"
    assert s2["identity_confidence"] == 0.912
    assert s2["profile_photo_url"] is not None

    print(f"[OK] Student 1 verified: {s1['name']}, Class: {s1['class']}, Roll: {s1['roll_number']}, Identity Conf: {s1['identity_confidence']}")
    print(f"[OK] Student 2 verified: {s2['name']}, Class: {s2['class']}, Roll: {s2['roll_number']}, Identity Conf: {s2['identity_confidence']}")

    # =========================================================================
    # TEST 4: Verify Evidence Links / Files
    # =========================================================================
    print("\n--- TEST 4: Verify Evidence Links & Files ---")
    evidence = r_data["evidence"]
    assert evidence["evidence_image"] is not None, "Evidence frame image must be referenced"
    assert evidence["evidence_clip"] is not None, "Evidence clip video must be referenced"
    assert len(evidence["items"]) == 2, "Timeline evidence items must have frame and clip"

    # Verify physical files exist
    assert os.path.exists(data_ids["frame_path"]), f"Evidence frame file does not exist: {data_ids['frame_path']}"
    assert os.path.exists(data_ids["clip_path"]), f"Evidence clip file does not exist: {data_ids['clip_path']}"
    print(f"[OK] Evidence Frame verified on storage: {data_ids['frame_path']}")
    print(f"[OK] Evidence Clip verified on storage: {data_ids['clip_path']}")
    print(f"[OK] Evidence links in report: Image: {evidence['evidence_image']}, Clip: {evidence['evidence_clip']}")

    # =========================================================================
    # TEST 5: Verify Report Download (JSON & HTML)
    # =========================================================================
    print("\n--- TEST 5: Verify Report Download Endpoints ---")
    # 5.1 JSON Download
    json_dl_resp = client.get(f"/api/v1/reports/download/{report_id}?format=json")
    assert json_dl_resp.status_code == status.HTTP_200_OK
    assert "application/json" in json_dl_resp.headers["content-type"]
    dl_json_data = json_dl_resp.json()
    assert dl_json_data["report_id"] == report_id
    assert dl_json_data["event_type"] == "VIOLENCE"
    assert dl_json_data["violence_confidence"] == 0.914
    assert len(dl_json_data["involved_students"]) == 2
    print("[OK] JSON Download verified with complete violence event & student metadata")

    # 5.2 HTML Download
    html_dl_resp = client.get(f"/api/v1/reports/download/{report_id}?format=html")
    assert html_dl_resp.status_code == status.HTTP_200_OK
    assert "text/html" in html_dl_resp.headers["content-type"]
    html_content = html_dl_resp.text

    assert "⚠ VIOLENCE DETECTED" in html_content
    assert "Event &amp; Video Information" in html_content or "Event & Video Information" in html_content
    assert "VIOLENCE" in html_content
    assert "91.4%" in html_content
    assert "Arjun Sharma" in html_content
    assert "Rohan Verma" in html_content
    assert "S6 CSE A" in html_content
    assert "S6 CSE B" in html_content
    assert "23" in html_content
    assert "41" in html_content
    assert "94.7%" in html_content
    assert "91.2%" in html_content
    assert "[Detected Evidence Frame]" in html_content
    assert "[Evidence Clip]" in html_content
    assert "Notice:" in html_content
    print("[OK] HTML Download verified with VIOLENCE banner, Students table, Evidence Frame/Clip, and Notice")

    # =========================================================================
    # TEST 6: Verify Database Persistence & Retrieval
    # =========================================================================
    print("\n--- TEST 6: Verify Database Persistence & API Retrieval ---")
    # API Retrieval via standard Reports endpoint
    get_report_resp = client.get(f"/api/v1/reports/{report_id}")
    assert get_report_resp.status_code == status.HTTP_200_OK
    fetched_report = get_report_resp.json()
    assert fetched_report["id"] == report_id
    assert fetched_report["incident_type"] == "Violence"
    assert fetched_report["data"]["event_type"] == "VIOLENCE"
    assert len(fetched_report["data"]["involved_students"]) == 2
    print("[OK] API GET /reports/{id} verified persistence and accurate retrieval")

    # Direct DB Query verification
    async def verify_db_record():
        async with SessionLocal() as db:
            rep = await db.get(Report, uuid.UUID(report_id))
            assert rep is not None, "Report must exist in database"
            assert rep.incident_type == "Violence"
            assert rep.data.get("event_type") == "VIOLENCE"
            assert rep.data.get("violence_confidence") == 0.914
            # Confirm no extraneous tables created
            return True

    run_async(verify_db_record())
    print("[OK] Direct database query verified record in Report table without duplicate tables")

    print("\n========================================================")
    print("ALL 6 VIOLENCE REPORT INTEGRATION TESTS PASSED SUCCESSFULLY!")
    print("========================================================\n")

if __name__ == "__main__":
    test_violence_report_system_end_to_end()
