"""
Phase F6 Comprehensive Test Suite:
Validates real-time video processing progress pipeline,
monotonic progress guarantees, failure handling, cancellation handling,
API responses, and polling criteria.
"""

import os
import sys
import uuid
import asyncio
import sqlite3
from datetime import datetime, timezone

os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/cctv.db"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.user import User
from app.models.camera import Camera
from app.models.video import Video
from app.tasks.video_tasks import (
    _update_video_progress,
    is_video_cancelled,
    cancel_video_processing,
    VideoProcessingCancelledException
)
from app.schemas.video import VideoResponse, VideoStatusResponse

DB_PATH = os.path.abspath(os.path.join(backend_path, "storage", "cctv.db"))

async def test_initial_video_creation_and_fields():
    """1. Test that newly created/uploaded video has queued status, 0% progress, and stage Queued."""
    async with SessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        assert user, "User must exist in database"
        
        vid_id = uuid.uuid4()
        video = Video(
            id=vid_id,
            title="F6 Ingest Test",
            filename=f"f6_test_{vid_id.hex[:6]}.mp4",
            original_filename="f6_test.mp4",
            file_path=f"/fake/{vid_id}.mp4",
            status="queued",
            current_stage="Queued",
            progress_percentage=0,
            uploaded_by=user.id
        )
        db.add(video)
        await db.commit()
        await db.refresh(video)

        assert video.status == "queued"
        assert video.current_stage == "Queued"
        assert video.progress_percentage == 0

        # Verify schema serialization
        schema = VideoResponse.model_validate(video)
        assert schema.status == "queued"
        assert schema.current_stage == "Queued"
        assert schema.progress_percentage == 0

        await db.delete(video)
        await db.commit()

async def test_staged_progress_pipeline_and_monotonicity():
    """2. Test staged progress progression and verify progress is monotonic."""
    async with SessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        vid_id = uuid.uuid4()
        video = Video(
            id=vid_id,
            title="F6 Monotonic Test",
            filename=f"f6_mono_{vid_id.hex[:6]}.mp4",
            original_filename="f6_mono.mp4",
            file_path=f"/fake/{vid_id}.mp4",
            status="queued",
            current_stage="Queued",
            progress_percentage=0,
            uploaded_by=user.id
        )
        db.add(video)
        await db.commit()

    # Step A: Initialization (0%)
    await _update_video_progress(
        video_id=vid_id,
        status="processing",
        stage="Initialization",
        progress=0,
        started_at=datetime.now(timezone.utc)
    )

    async with SessionLocal() as db:
        v = (await db.execute(select(Video).filter(Video.id == vid_id))).scalars().first()
        assert v.status == "processing"
        assert v.current_stage == "Initialization"
        assert v.progress_percentage == 0

    # Step B: Frame Extraction (15%)
    await _update_video_progress(
        video_id=vid_id,
        status="processing",
        stage="Frame Extraction & Detection",
        progress=15
    )
    async with SessionLocal() as db:
        v = (await db.execute(select(Video).filter(Video.id == vid_id))).scalars().first()
        assert v.current_stage == "Frame Extraction & Detection"
        assert v.progress_percentage == 15

    # Step C: Detection & Tracking (35%)
    await _update_video_progress(
        video_id=vid_id,
        status="processing",
        stage="Detection & Tracking",
        progress=35
    )
    async with SessionLocal() as db:
        v = (await db.execute(select(Video).filter(Video.id == vid_id))).scalars().first()
        assert v.current_stage == "Detection & Tracking"
        assert v.progress_percentage == 35

    # Step D: Test Monotonicity - A late callback reporting 20% should NOT lower 35%
    await _update_video_progress(
        video_id=vid_id,
        status="processing",
        stage="Detection & Tracking (Late Callback)",
        progress=20
    )
    async with SessionLocal() as db:
        v = (await db.execute(select(Video).filter(Video.id == vid_id))).scalars().first()
        assert v.progress_percentage == 35, f"Progress must remain monotonic: expected 35 but got {v.progress_percentage}"

    # Step E: Violence Segments (60%) preservation
    await _update_video_progress(
        video_id=vid_id,
        status="processing",
        stage="Processing Violence Segments (YOLOv8 & ByteTrack)",
        progress=60
    )
    async with SessionLocal() as db:
        v = (await db.execute(select(Video).filter(Video.id == vid_id))).scalars().first()
        assert v.current_stage == "Processing Violence Segments (YOLOv8 & ByteTrack)"
        assert v.progress_percentage == 60

    # Step F: Face Recognition (85%)
    await _update_video_progress(
        video_id=vid_id,
        status="processing",
        stage="Face Recognition",
        progress=85
    )
    async with SessionLocal() as db:
        v = (await db.execute(select(Video).filter(Video.id == vid_id))).scalars().first()
        assert v.current_stage == "Face Recognition"
        assert v.progress_percentage == 85

    # Step G: Metadata Storage (90%)
    await _update_video_progress(
        video_id=vid_id,
        status="processing",
        stage="Metadata Storage",
        progress=90
    )
    async with SessionLocal() as db:
        v = (await db.execute(select(Video).filter(Video.id == vid_id))).scalars().first()
        assert v.current_stage == "Metadata Storage"
        assert v.progress_percentage == 90

    # Step H: Cannot show 100% while still processing
    await _update_video_progress(
        video_id=vid_id,
        status="processing",
        stage="Almost Done",
        progress=100
    )
    async with SessionLocal() as db:
        v = (await db.execute(select(Video).filter(Video.id == vid_id))).scalars().first()
        assert v.progress_percentage == 99, "Processing status must not show 100% until genuinely completed"

    # Step I: Completed (100%)
    await _update_video_progress(
        video_id=vid_id,
        status="completed",
        stage="Completed",
        progress=100,
        finished_at=datetime.now(timezone.utc)
    )
    async with SessionLocal() as db:
        v = (await db.execute(select(Video).filter(Video.id == vid_id))).scalars().first()
        assert v.status == "completed"
        assert v.current_stage == "Completed"
        assert v.progress_percentage == 100
        assert v.processing_finished_at is not None

        # Clean up
        await db.delete(v)
        await db.commit()

async def test_failure_handling_and_no_fake_100():
    """3. Test that task failures preserve achieved progress and never report 100%."""
    async with SessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        vid_id = uuid.uuid4()
        video = Video(
            id=vid_id,
            title="F6 Failure Test",
            filename=f"f6_fail_{vid_id.hex[:6]}.mp4",
            original_filename="f6_fail.mp4",
            file_path=f"/fake/{vid_id}.mp4",
            status="processing",
            current_stage="Detection & Tracking",
            progress_percentage=45,
            uploaded_by=user.id
        )
        db.add(video)
        await db.commit()

    # Simulate pipeline error at 45%
    await _update_video_progress(
        video_id=vid_id,
        status="failed",
        stage="Failed",
        progress=0,
        finished_at=datetime.now(timezone.utc),
        error_message="Test pipeline failure"
    )

    async with SessionLocal() as db:
        v = (await db.execute(select(Video).filter(Video.id == vid_id))).scalars().first()
        assert v.status == "failed"
        assert v.current_stage == "Failed"
        assert v.progress_percentage == 45, f"Failure must preserve actual progress (45), got {v.progress_percentage}"
        assert v.progress_percentage != 100, "Failure must NEVER display 100%"
        assert v.error_message == "Test pipeline failure"

        await db.delete(v)
        await db.commit()

async def test_cancellation_suppresses_subsequent_updates():
    """4. Test that cancelled/deleted videos reject subsequent progress updates."""
    async with SessionLocal() as db:
        user = (await db.execute(select(User))).scalars().first()
        vid_id = uuid.uuid4()
        video = Video(
            id=vid_id,
            title="F6 Cancel Test",
            filename=f"f6_can_{vid_id.hex[:6]}.mp4",
            original_filename="f6_can.mp4",
            file_path=f"/fake/{vid_id}.mp4",
            status="processing",
            current_stage="Frame Extraction",
            progress_percentage=20,
            uploaded_by=user.id
        )
        db.add(video)
        await db.commit()

    # Cancel video
    cancel_video_processing(vid_id)
    assert is_video_cancelled(vid_id) is True

    # Attempt progress update after cancellation
    await _update_video_progress(
        video_id=vid_id,
        status="processing",
        stage="Embeddings",
        progress=70
    )

    # In DB, stage should still be Frame Extraction and 20%
    async with SessionLocal() as db:
        v = (await db.execute(select(Video).filter(Video.id == vid_id))).scalars().first()
        assert v.current_stage == "Frame Extraction"
        assert v.progress_percentage == 20

        # Clean up
        await db.delete(v)
        await db.commit()

def test_sqlite_db_integrity():
    """5. Verify SQLite integrity and videos foreign keys."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA integrity_check;")
    assert cursor.fetchall() == [("ok",)]
    cursor.execute("PRAGMA foreign_key_check('videos');")
    assert cursor.fetchall() == []
    conn.close()

async def run_all_f6_tests():
    print("============================================================")
    print("RUNNING PHASE F6 REAL-TIME PROGRESS TEST SUITE")
    print("============================================================")

    print("\n--- TEST 1: Initial Video Fields & Queued Status ---")
    await test_initial_video_creation_and_fields()
    print("[OK] Video created with status queued, stage Queued, 0% progress.")

    print("\n--- TEST 2: Staged Progress & Monotonicity ---")
    await test_staged_progress_pipeline_and_monotonicity()
    print("[OK] Staged pipeline transitions verified; monotonic rule enforced.")

    print("\n--- TEST 3: Failure Handling & 100% Guard ---")
    await test_failure_handling_and_no_fake_100()
    print("[OK] Failure preserves actual progress and does not show 100%.")

    print("\n--- TEST 4: Cancellation Suppresses Subsequent Updates ---")
    await test_cancellation_suppresses_subsequent_updates()
    print("[OK] Cancelled video ignores late worker updates.")

    print("\n--- TEST 5: SQLite Database Integrity ---")
    test_sqlite_db_integrity()
    print("[OK] SQLite integrity and foreign key checks passed with 0 violations.")

    print("\n============================================================")
    print("ALL PHASE F6 TESTS PASSED SUCCESSFULLY!")
    print("============================================================")

if __name__ == "__main__":
    asyncio.run(run_all_f6_tests())
