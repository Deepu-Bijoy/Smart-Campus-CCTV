import asyncio
import os
import sys
import uuid
import tempfile
import cv2
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Set fallback environment flags before imports
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_fight_detector.db"

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

from fastapi.testclient import TestClient
from fastapi import status
from app.main import app
from app.api import deps
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.models.user import User
from app.models.video import Video
from app.models.camera import Camera
from app.models.track import Track, Detection
from app.models.incident import Incident, DetectedEvent
from app.event_engine.event_engine import FightDetector

client = TestClient(app)

async def init_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

def test_fight_detector_suite():
    print("\n=======================================================")
    print("  RUNNING FIGHT DETECTOR INTEGRATION TEST SUITE")
    print("=======================================================")
    asyncio.run(init_test_db())

    # Setup mock user dependency override
    mock_user_id = uuid.uuid4()
    mock_user = User(
        id=mock_user_id,
        email="security@smartcampus.edu",
        hashed_password="fakehashedpassword",
        full_name="Senior Security Analyst",
        is_active=True
    )
    app.dependency_overrides[deps.get_current_user] = lambda: mock_user

    async def get_test_db():
        async with SessionLocal() as session:
            yield session
    app.dependency_overrides[deps.get_db] = get_test_db

    # Setup Camera
    camera_id = uuid.uuid4()
    async def create_camera():
        async with SessionLocal() as db:
            cam = Camera(
                id=camera_id,
                name="North Gate CCTV",
                building="Main Admin Block",
                floor=1,
                location="Main Campus Entrance",
                direction="North",
                resolution="1920x1080",
                status="active"
            )
            db.add(cam)
            await db.commit()
    asyncio.run(create_camera())

    # 1. Direct unit verification of existing FightDetector algorithm
    print("\n[TEST 1] Testing existing FightDetector algorithm directly...")
    detector = FightDetector()

    # Track 1: Violent rapid motion
    t1 = Track(id=uuid.uuid4(), video_id=uuid.uuid4(), object_class="person", tracker_id=1, start_time=0.0, end_time=10.0)
    d1 = Detection(id=uuid.uuid4(), track_id=t1.id, frame_number=0, timestamp_seconds=4.0, bounding_box=[100.0, 100.0, 150.0, 250.0], confidence=0.9)
    d2 = Detection(id=uuid.uuid4(), track_id=t1.id, frame_number=25, timestamp_seconds=5.0, bounding_box=[250.0, 180.0, 300.0, 330.0], confidence=0.9) # Rapid movement
    t1.detections = [d1, d2]

    # Track 2: Interacting close by
    t2 = Track(id=uuid.uuid4(), video_id=uuid.uuid4(), object_class="person", tracker_id=2, start_time=0.0, end_time=10.0)
    d3 = Detection(id=uuid.uuid4(), track_id=t2.id, frame_number=0, timestamp_seconds=4.0, bounding_box=[130.0, 110.0, 180.0, 260.0], confidence=0.9)
    d4 = Detection(id=uuid.uuid4(), track_id=t2.id, frame_number=25, timestamp_seconds=5.0, bounding_box=[260.0, 190.0, 310.0, 340.0], confidence=0.9) # High proximity (<50px)
    t2.detections = [d3, d4]

    violent_score, violent_breakdown = detector.analyze([t1, t2], clip_score=0.32, match_time_sec=5.0)
    print(f"  --> Violent scenario score: {violent_score:.2f}, breakdown: {violent_breakdown}")
    assert violent_score >= 0.70, f"Expected fight score >= 0.70, got {violent_score}"
    assert violent_breakdown["motion_dynamics"] > 0.80
    assert violent_breakdown["person_interaction"] > 0.80

    # Non-violent stationary tracks
    t_slow1 = Track(id=uuid.uuid4(), video_id=uuid.uuid4(), object_class="person", tracker_id=3, start_time=0.0, end_time=10.0)
    ds1 = Detection(id=uuid.uuid4(), track_id=t_slow1.id, frame_number=0, timestamp_seconds=4.0, bounding_box=[100.0, 100.0, 150.0, 250.0], confidence=0.9)
    ds2 = Detection(id=uuid.uuid4(), track_id=t_slow1.id, frame_number=25, timestamp_seconds=5.0, bounding_box=[102.0, 101.0, 152.0, 251.0], confidence=0.9) # Barely moved
    t_slow1.detections = [ds1, ds2]

    calm_score, calm_breakdown = detector.analyze([t_slow1], clip_score=0.10, match_time_sec=5.0)
    print(f"  --> Non-violent scenario score: {calm_score:.2f}, breakdown: {calm_breakdown}")
    assert calm_score < 0.30, f"Expected calm score < 0.30, got {calm_score}"
    print("  --> PASSED: Existing FightDetector multi-signal mathematical model verified.")

    # 2. Test End-to-End Workflow with Known Non-Violent Video
    print("\n[TEST 2] Testing workflow with known non-violent video...")
    non_violent_video_id = uuid.uuid4()
    async def create_non_violent_video():
        async with SessionLocal() as db:
            vid = Video(
                id=non_violent_video_id,
                title="Library Hallway Normal Feed",
                filename="library_calm.mp4",
                original_filename="library_calm.mp4",
                file_path="storage/library_calm.mp4",
                status="uploaded",
                duration=30.0,
                width=1920,
                height=1080,
                fps=30.0,
                uploaded_by=mock_user_id,
                camera_id=camera_id
            )
            db.add(vid)
            await db.commit()
    asyncio.run(create_non_violent_video())

    # Call POST /api/v1/violence/analyze with video_id (no incidents exist)
    response = client.post(
        "/api/v1/violence/analyze",
        data={"video_id": str(non_violent_video_id)}
    )
    assert response.status_code == status.HTTP_200_OK, f"Analysis failed: {response.text}"
    non_violent_data = response.json()
    assert non_violent_data["status"] == "NORMAL"
    assert non_violent_data["total_segments"] == 0
    assert non_violent_data["overall_confidence"] == 0.0
    assert "Normal campus activity verified" in non_violent_data["verdict"]
    print(f"  --> PASSED: Correctly evaluated as NORMAL. Verdict: {non_violent_data['verdict']}")

    # 3. Test End-to-End Workflow with Known Violent Video (Single Altercation Segment)
    print("\n[TEST 3] Testing workflow with known violent video & verifying timestamps/confidence...")
    violent_video_id = uuid.uuid4()
    created_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    async def create_violent_video_and_incident():
        async with SessionLocal() as db:
            vid = Video(
                id=violent_video_id,
                title="Cafeteria Clash CCTV",
                filename="cafeteria_fight.mp4",
                original_filename="cafeteria_fight.mp4",
                file_path="storage/cafeteria_fight.mp4",
                status="uploaded",
                duration=45.0,
                width=1920,
                height=1080,
                fps=30.0,
                uploaded_by=mock_user_id,
                camera_id=camera_id,
                created_at=created_time
            )
            db.add(vid)

            # Insert fight incident at timestamp 12.0s
            inc_id = uuid.uuid4()
            inc = Incident(
                id=inc_id,
                incident_type="Fight",
                timestamp=created_time + timedelta(seconds=12.0),
                camera_id=camera_id,
                confidence=0.88,
                explanation="Detected physical fight/altercation at 12.0s on camera North Gate CCTV. Multi-signal breakdown: Motion dynamics: 0.94, Interaction proximity: 0.90, CLIP score: 0.78."
            )
            db.add(inc)

            det_event = DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc_id,
                event_type="FIGHT",
                camera_id=camera_id,
                video_id=violent_video_id,
                timestamp=created_time + timedelta(seconds=12.0),
                confidence=0.88
            )
            db.add(det_event)
            await db.commit()
    asyncio.run(create_violent_video_and_incident())

    response = client.post(
        "/api/v1/violence/analyze",
        data={"video_id": str(violent_video_id)}
    )
    assert response.status_code == status.HTTP_200_OK, f"Analysis failed: {response.text}"
    violent_data = response.json()
    assert violent_data["status"] == "VIOLENCE_DETECTED"
    assert violent_data["total_segments"] == 1
    assert violent_data["overall_confidence"] == 0.88

    segment = violent_data["segments"][0]
    # Timestamp at 12.0s: start_time = max(0, 12 - 2.5) = 9.5s, end_time = 9.5 + 6.0 = 15.5s
    assert segment["start_time"] == 9.5, f"Expected 9.5s, got {segment['start_time']}"
    assert segment["end_time"] == 15.5, f"Expected 15.5s, got {segment['end_time']}"
    assert segment["duration"] == 6.0
    assert segment["confidence"] == 0.88
    assert segment["severity"] == "High"
    assert segment["breakdown"]["motion_dynamics"] == 0.94
    assert segment["breakdown"]["person_interaction"] == 0.90
    print(f"  --> PASSED: Detected segment at {segment['timestamp_display']} ({segment['start_time']}s - {segment['end_time']}s) with {segment['confidence']} confidence.")

    # 4. Test Multiple Violence Segments in Single Video
    print("\n[TEST 4] Testing multiple violence segments detection in a single video...")
    multi_video_id = uuid.uuid4()
    async def create_multi_segment_video():
        async with SessionLocal() as db:
            vid = Video(
                id=multi_video_id,
                title="Grounds Multi-Altercation Stream",
                filename="grounds_stream.mp4",
                original_filename="grounds_stream.mp4",
                file_path="storage/grounds_stream.mp4",
                status="uploaded",
                duration=60.0,
                width=1920,
                height=1080,
                fps=30.0,
                uploaded_by=mock_user_id,
                camera_id=camera_id,
                created_at=created_time
            )
            db.add(vid)

            # Segment 1 at 8.0s (confidence 0.76)
            inc1_id = uuid.uuid4()
            inc1 = Incident(
                id=inc1_id,
                incident_type="Fight",
                timestamp=created_time + timedelta(seconds=8.0),
                camera_id=camera_id,
                confidence=0.76,
                explanation="Detected physical fight/altercation at 8.0s on camera North Gate CCTV. Multi-signal breakdown: Motion dynamics: 0.80, Interaction proximity: 0.75, CLIP score: 0.70."
            )
            db.add(inc1)
            db.add(DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc1_id,
                event_type="FIGHT",
                camera_id=camera_id,
                video_id=multi_video_id,
                timestamp=created_time + timedelta(seconds=8.0),
                confidence=0.76
            ))

            # Segment 2 at 35.0s (confidence 0.92)
            inc2_id = uuid.uuid4()
            inc2 = Incident(
                id=inc2_id,
                incident_type="Fight",
                timestamp=created_time + timedelta(seconds=35.0),
                camera_id=camera_id,
                confidence=0.92,
                explanation="Detected physical fight/altercation at 35.0s on camera North Gate CCTV. Multi-signal breakdown: Motion dynamics: 0.96, Interaction proximity: 0.92, CLIP score: 0.85."
            )
            db.add(inc2)
            db.add(DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc2_id,
                event_type="FIGHT",
                camera_id=camera_id,
                video_id=multi_video_id,
                timestamp=created_time + timedelta(seconds=35.0),
                confidence=0.92
            ))
            await db.commit()
    asyncio.run(create_multi_segment_video())

    response = client.post(
        "/api/v1/violence/analyze",
        data={"video_id": str(multi_video_id)}
    )
    assert response.status_code == status.HTTP_200_OK, f"Analysis failed: {response.text}"
    multi_data = response.json()
    assert multi_data["status"] == "VIOLENCE_DETECTED"
    assert multi_data["total_segments"] == 2
    assert multi_data["overall_confidence"] == 0.92
    assert len(multi_data["segments"]) == 2

    seg1 = multi_data["segments"][0]
    seg2 = multi_data["segments"][1]
    assert seg1["start_time"] == 5.5 and seg1["end_time"] == 11.5
    assert seg2["start_time"] == 32.5 and seg2["end_time"] == 38.5
    print(f"  --> PASSED: Segment 1 at {seg1['timestamp_display']} (Conf: {seg1['confidence']})")
    print(f"  --> PASSED: Segment 2 at {seg2['timestamp_display']} (Conf: {seg2['confidence']})")

    # 5. Test Dedicated GET /result/{video_id} and GET /status/{video_id} Endpoints
    print("\n[TEST 5] Testing GET /result/{video_id} and GET /status/{video_id} retrieval endpoints...")
    res_status = client.get(f"/api/v1/violence/status/{multi_video_id}")
    assert res_status.status_code == status.HTTP_200_OK
    assert res_status.json()["status"] == "completed"
    assert res_status.json()["progress"] == 100
    print(f"  --> PASSED: Status endpoint returned: {res_status.json()}")

    res_result = client.get(f"/api/v1/violence/result/{multi_video_id}")
    assert res_result.status_code == status.HTTP_200_OK
    assert res_result.json()["total_segments"] == 2
    assert res_result.json()["video_id"] == str(multi_video_id)
    print(f"  --> PASSED: Result endpoint returned valid dossier for video {multi_video_id}.")

    print("\n=======================================================")
    print("  ALL FIGHT DETECTOR INTEGRATION TESTS PASSED (5/5)!")
    print("=======================================================\n")

if __name__ == "__main__":
    test_fight_detector_suite()
