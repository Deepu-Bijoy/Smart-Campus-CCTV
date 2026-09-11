import asyncio
import os
import sys
import uuid
import cv2
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

# Set fallback environment flags before imports
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_evidence_gen.db"

# Mock heavy deep learning modules before backend imports
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
from app.main import app
from app.api import deps
from app.core.config import settings
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.models.user import User
from app.models.video import Video
from app.models.camera import Camera
from app.models.incident import Incident, DetectedEvent, Evidence
from app.services.clip_generator import generate_subclip, extract_evidence_frame
from app.api.v1.violence import _compile_violence_dossier

client = TestClient(app)

def create_synthetic_mp4(filepath: str, duration_sec: float = 10.0, fps: float = 25.0):
    """Creates a real valid synthetic mp4 file using OpenCV VideoWriter."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    total_frames = int(duration_sec * fps)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filepath, fourcc, fps, (320, 240))
    for i in range(total_frames):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        # Visual indicator: a moving white block
        x = int((i / max(1, total_frames)) * 260)
        cv2.rectangle(frame, (x, 100), (x + 40, 140), (255, 255, 255), -1)
        cv2.putText(frame, f"T:{i/fps:.1f}s", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
        out.write(frame)
    out.release()

async def init_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

def run_evidence_generation_tests():
    print("\n=======================================================")
    print("  RUNNING VIOLENCE EVIDENCE GENERATION TEST SUITE")
    print("=======================================================")
    asyncio.run(init_test_db())

    storage_dir = settings.STORAGE_DIR
    os.makedirs(os.path.join(storage_dir, "evidence"), exist_ok=True)
    os.makedirs(storage_dir, exist_ok=True)

    # 1. Setup camera and test video files
    cam_id = uuid.uuid4()
    user_id = uuid.uuid4()
    async def seed_camera():
        async with SessionLocal() as db:
            user = User(
                id=user_id,
                email="investigator@smartcampus.edu",
                hashed_password="fakepassword",
                role="admin"
            )
            db.add(user)
            cam = Camera(
                id=cam_id,
                name="Courtyard South CCTV",
                building="Student Activities Center",
                floor="Ground Floor",
                location="Courtyard Lawn",
                direction="South-West",
                resolution="1920x1080",
                status="active"
            )
            db.add(cam)
            await db.commit()
    asyncio.run(seed_camera())

    # Create a 30-second synthetic test video
    real_video_path = os.path.join(storage_dir, "evidence_test_source.mp4")
    create_synthetic_mp4(real_video_path, duration_sec=30.0, fps=25.0)

    # --- TEST 1: Single Violence Event ---
    print("\n[TEST 1] Testing single violence event evidence generation...")
    v1_id = uuid.uuid4()
    inc1_id = uuid.uuid4()
    det1_id = uuid.uuid4()
    base_time = datetime.now(timezone.utc)

    async def setup_single_event():
        async with SessionLocal() as db:
            v1 = Video(
                id=v1_id,
                title="Courtyard Violence Test 1",
                filename="evidence_test_source.mp4",
                original_filename="courtyard_fight.mp4",
                file_path=real_video_path,
                status="completed",
                duration=30.0,
                width=320,
                height=240,
                fps=25.0,
                file_size=os.path.getsize(real_video_path),
                camera_id=cam_id,
                uploaded_by=user_id,
                created_at=base_time
            )
            db.add(v1)

            inc1 = Incident(
                id=inc1_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=12.0),
                camera_id=cam_id,
                confidence=0.91,
                explanation="Physical struggle detected at 12.0s. Motion dynamics: 0.94, Interaction proximity: 0.92, CLIP score: 0.81."
            )
            db.add(inc1)

            det1 = DetectedEvent(
                id=det1_id,
                incident_id=inc1_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v1_id,
                timestamp=base_time + timedelta(seconds=12.0),
                confidence=0.91
            )
            db.add(det1)
            await db.commit()
            
            cam_obj = await db.get(Camera, cam_id)
            dossier = await _compile_violence_dossier(db, v1, cam_obj)
            return dossier

    dossier1 = asyncio.run(setup_single_event())
    assert dossier1.status == "VIOLENCE_DETECTED"
    assert dossier1.total_segments == 1
    seg1 = dossier1.segments[0]

    # Verify associations
    assert seg1.segment_id == str(inc1_id)
    assert seg1.event_id == str(det1_id)
    assert seg1.video_id == str(v1_id)
    assert seg1.start_time == 9.5
    assert seg1.end_time == 15.5
    assert seg1.duration == 6.0
    assert seg1.timestamp_display == "00:00:09 - 00:00:15"
    assert seg1.confidence == 0.91

    # Verify evidence image and clip were generated and exist on disk
    assert seg1.evidence_image is not None, "Evidence image should not be None"
    assert seg1.evidence_video is not None, "Evidence video should not be None"
    img_filename = f"evidence_frame_{inc1_id.hex}.jpg"
    img_disk_path = os.path.join(storage_dir, "evidence", img_filename)
    assert os.path.exists(img_disk_path), f"Evidence image was not created at {img_disk_path}"
    assert os.path.getsize(img_disk_path) > 0, "Evidence image size is 0 bytes"
    print(f"  --> Representative frame verified: {img_disk_path} ({os.path.getsize(img_disk_path)} bytes)")

    clip_filename = f"clip_{inc1_id.hex}.mp4"
    clip_disk_path = os.path.join(storage_dir, "evidence", clip_filename)
    assert os.path.exists(clip_disk_path), f"Evidence clip was not created at {clip_disk_path}"
    assert os.path.getsize(clip_disk_path) > 0, "Evidence clip size is 0 bytes"
    print(f"  --> Evidence clip verified: {clip_disk_path} ({os.path.getsize(clip_disk_path)} bytes)")
    print(f"  --> Formatted timestamp: {seg1.timestamp_display}")
    print("  --> PASSED: Single violence event evidence generated & associated correctly.")

    # --- TEST 2: Multiple Violence Events ---
    print("\n[TEST 2] Testing multiple violence events in a single video...")
    v2_id = uuid.uuid4()
    inc2_a_id = uuid.uuid4()
    inc2_b_id = uuid.uuid4()

    async def setup_multiple_events():
        async with SessionLocal() as db:
            v2 = Video(
                id=v2_id,
                title="Cafeteria Multiple Fights",
                filename="evidence_test_source.mp4",
                original_filename="cafeteria_cctv.mp4",
                file_path=real_video_path,
                status="completed",
                duration=30.0,
                width=320,
                height=240,
                fps=25.0,
                file_size=os.path.getsize(real_video_path),
                camera_id=cam_id,
                uploaded_by=user_id,
                created_at=base_time
            )
            db.add(v2)

            inc_a = Incident(
                id=inc2_a_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=5.0),
                camera_id=cam_id,
                confidence=0.85,
                explanation="Physical struggle detected at 5.0s. Motion dynamics: 0.88."
            )
            det_a = DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc2_a_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v2_id,
                timestamp=base_time + timedelta(seconds=5.0),
                confidence=0.85
            )
            db.add(inc_a)
            db.add(det_a)

            inc_b = Incident(
                id=inc2_b_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=22.0),
                camera_id=cam_id,
                confidence=0.94,
                explanation="Physical struggle detected at 22.0s. Motion dynamics: 0.96."
            )
            det_b = DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc2_b_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v2_id,
                timestamp=base_time + timedelta(seconds=22.0),
                confidence=0.94
            )
            db.add(inc_b)
            db.add(det_b)
            await db.commit()

            cam_obj = await db.get(Camera, cam_id)
            dossier = await _compile_violence_dossier(db, v2, cam_obj)
            return dossier

    dossier2 = asyncio.run(setup_multiple_events())
    assert dossier2.status == "VIOLENCE_DETECTED"
    assert dossier2.total_segments == 2
    assert len(dossier2.segments) == 2
    assert dossier2.segments[0].timestamp_display == "00:00:02 - 00:00:08"
    assert dossier2.segments[1].timestamp_display == "00:00:19 - 00:00:25"
    assert dossier2.segments[0].evidence_image is not None
    assert dossier2.segments[1].evidence_image is not None
    print(f"  --> Segment 1: {dossier2.segments[0].timestamp_display} (Confidence: {dossier2.segments[0].confidence})")
    print(f"  --> Segment 2: {dossier2.segments[1].timestamp_display} (Confidence: {dossier2.segments[1].confidence})")
    print("  --> PASSED: Multiple violence events generated distinct evidence and bookmarks.")

    # --- TEST 3: Event Near Beginning of Video ---
    print("\n[TEST 3] Testing event near beginning of video (t = 0.5s)...")
    v3_id = uuid.uuid4()
    inc3_id = uuid.uuid4()

    async def setup_start_event():
        async with SessionLocal() as db:
            v3 = Video(
                id=v3_id,
                title="Early Altercation",
                filename="evidence_test_source.mp4",
                original_filename="early_altercation.mp4",
                file_path=real_video_path,
                status="completed",
                duration=30.0,
                width=320,
                height=240,
                fps=25.0,
                file_size=os.path.getsize(real_video_path),
                camera_id=cam_id,
                uploaded_by=user_id,
                created_at=base_time
            )
            db.add(v3)

            inc3 = Incident(
                id=inc3_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=0.5),
                camera_id=cam_id,
                confidence=0.88,
                explanation="Altercation at 0.5s."
            )
            det3 = DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc3_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v3_id,
                timestamp=base_time + timedelta(seconds=0.5),
                confidence=0.88
            )
            db.add(inc3)
            db.add(det3)
            await db.commit()

            cam_obj = await db.get(Camera, cam_id)
            dossier = await _compile_violence_dossier(db, v3, cam_obj)
            return dossier

    dossier3 = asyncio.run(setup_start_event())
    seg3 = dossier3.segments[0]
    # start_time must not be negative
    assert seg3.start_time >= 0.0, f"Expected start_time >= 0.0, got {seg3.start_time}"
    assert seg3.timestamp_display == "00:00:00 - 00:00:06"
    assert seg3.evidence_image is not None
    assert seg3.evidence_video is not None
    print(f"  --> Beginning bounded cleanly: {seg3.timestamp_display} (start={seg3.start_time}s, end={seg3.end_time}s)")
    print("  --> PASSED: Event near beginning properly clamped without negative indices.")

    # --- TEST 4: Event Near End of Video ---
    print("\n[TEST 4] Testing event near end of video (t = 29.5s of 30.0s video)...")
    v4_id = uuid.uuid4()
    inc4_id = uuid.uuid4()

    async def setup_end_event():
        async with SessionLocal() as db:
            v4 = Video(
                id=v4_id,
                title="Late Altercation",
                filename="evidence_test_source.mp4",
                original_filename="late_altercation.mp4",
                file_path=real_video_path,
                status="completed",
                duration=30.0,
                width=320,
                height=240,
                fps=25.0,
                file_size=os.path.getsize(real_video_path),
                camera_id=cam_id,
                uploaded_by=user_id,
                created_at=base_time
            )
            db.add(v4)

            inc4 = Incident(
                id=inc4_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=29.5),
                camera_id=cam_id,
                confidence=0.92,
                explanation="Altercation at 29.5s."
            )
            det4 = DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc4_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v4_id,
                timestamp=base_time + timedelta(seconds=29.5),
                confidence=0.92
            )
            db.add(inc4)
            db.add(det4)
            await db.commit()

            cam_obj = await db.get(Camera, cam_id)
            dossier = await _compile_violence_dossier(db, v4, cam_obj)
            return dossier

    dossier4 = asyncio.run(setup_end_event())
    seg4 = dossier4.segments[0]
    assert seg4.end_time <= 30.0, f"Expected end_time <= 30.0, got {seg4.end_time}"
    assert seg4.start_time < seg4.end_time
    assert seg4.evidence_image is not None
    assert seg4.evidence_video is not None
    print(f"  --> End bounded cleanly: {seg4.timestamp_display} (start={seg4.start_time}s, end={seg4.end_time}s)")
    print("  --> PASSED: Event near end properly shifted within duration bounds.")

    # --- TEST 5: No Detected Violence ---
    print("\n[TEST 5] Testing video with no detected violence (NORMAL state)...")
    v5_id = uuid.uuid4()

    async def setup_normal_event():
        async with SessionLocal() as db:
            v5 = Video(
                id=v5_id,
                title="Calm Library Study",
                filename="evidence_test_source.mp4",
                original_filename="calm_study.mp4",
                file_path=real_video_path,
                status="completed",
                duration=30.0,
                camera_id=cam_id,
                uploaded_by=user_id,
                created_at=base_time
            )
            db.add(v5)
            await db.commit()

            cam_obj = await db.get(Camera, cam_id)
            dossier = await _compile_violence_dossier(db, v5, cam_obj)
            return dossier

    dossier5 = asyncio.run(setup_normal_event())
    assert dossier5.status == "NORMAL"
    assert dossier5.total_segments == 0
    assert len(dossier5.segments) == 0
    assert dossier5.primary_evidence_image is None
    assert dossier5.primary_evidence_video is None
    assert "Normal campus activity verified" in dossier5.verdict
    print(f"  --> Evaluated correctly as NORMAL: {dossier5.verdict}")
    print("  --> PASSED: No violence detected scenario correctly returns 0 segments and no evidence.")

    # --- TEST 6: Failed Frame Extraction Fallback ---
    print("\n[TEST 6] Testing graceful fallback when frame extraction fails...")
    # Attempt to extract frame from non-existent file
    bogus_path = os.path.join(storage_dir, "non_existent_corrupt.mp4")
    out_frame = os.path.join(storage_dir, "evidence", "fail_test_frame.jpg")
    frame_success = extract_evidence_frame(bogus_path, 5.0, out_frame)
    assert frame_success is False, "Frame extraction from non-existent video should return False"
    assert not os.path.exists(out_frame), "Failed frame file should not exist"

    # Verify dossier compiles with evidence_image=None when video file missing
    v6_id = uuid.uuid4()
    inc6_id = uuid.uuid4()
    async def setup_failed_frame():
        async with SessionLocal() as db:
            v6 = Video(
                id=v6_id,
                title="Missing Source Footage",
                filename="missing.mp4",
                original_filename="missing.mp4",
                file_path=bogus_path,
                status="completed",
                duration=10.0,
                camera_id=cam_id,
                uploaded_by=user_id,
                created_at=base_time
            )
            db.add(v6)

            inc6 = Incident(
                id=inc6_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=3.0),
                camera_id=cam_id,
                confidence=0.82,
                explanation="Altercation at 3.0s."
            )
            det6 = DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc6_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v6_id,
                timestamp=base_time + timedelta(seconds=3.0),
                confidence=0.82
            )
            db.add(inc6)
            db.add(det6)
            await db.commit()

            cam_obj = await db.get(Camera, cam_id)
            dossier = await _compile_violence_dossier(db, v6, cam_obj)
            return dossier

    dossier6 = asyncio.run(setup_failed_frame())
    assert dossier6.status == "VIOLENCE_DETECTED"
    assert dossier6.segments[0].evidence_image is None
    print(f"  --> Dossier compiled gracefully with evidence_image=None without crashing.")
    print("  --> PASSED: Failed frame extraction handled gracefully.")

    # --- TEST 7: Failed Clip Extraction Fallback ---
    print("\n[TEST 7] Testing graceful fallback when clip extraction fails...")
    out_clip = os.path.join(storage_dir, "evidence", "fail_test_clip.mp4")
    clip_success = generate_subclip(bogus_path, 5.0, 6.0, out_clip)
    assert clip_success is False, "Clip generation from non-existent video should return False"
    assert not os.path.exists(out_clip), "Failed clip file should not exist"
    assert dossier6.segments[0].evidence_video is None
    print(f"  --> Dossier compiled gracefully with evidence_video=None without crashing.")
    print("  --> PASSED: Failed clip extraction handled gracefully.")

    print("\n=======================================================")
    print("  ALL 7 EVIDENCE GENERATION TESTS PASSED (7/7)!")
    print("=======================================================\n")

if __name__ == "__main__":
    run_evidence_generation_tests()
