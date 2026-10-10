"""
Phase B Focused Test Suite: UUID Foreign-Key Compatibility & Non-Blocking Video Processing

Tests:
1. UUID Compatibility & Database Integrity:
   - Verification that SqliteCompatibleUUID binds uuid.UUID, 32-char hex, and 36-char hyphenated strings canonically.
   - Insertion of StudentRecognitionEvent referencing 36-char canonical UUID string.
   - Insertion of StudentRecognitionEvent referencing 32-char hex UUID string.
   - Verification under active PRAGMA foreign_keys=ON that both resolve to the same student record.
   - Rejection of invalid/non-existent student_id under PRAGMA foreign_keys=ON.
   - UUID bind/result round-trip fidelity.

2. Non-Blocking Video Upload & Celery Eager Execution:
   - process_video.delay() returns promptly (< 100ms) without blocking on inference.
   - Background execution transitions video status appropriately (queued -> processing).
   - Processing exception handling transitions video to failed with detailed error message.
   - Direct process_video.apply() continues to execute synchronously for test suites.
"""

import os
import sys
import uuid
import time
import asyncio
from unittest.mock import patch
import pytest
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
TEST_DB_PATH = os.path.abspath("./storage/test_phase_b.db")
os.environ["TEST_DATABASE_URI"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.core.config import settings
from app.db.base_class import Base, SqliteCompatibleUUID
from app.db.session import engine, SessionLocal
from app.models.user import User
from app.models.camera import Camera
from app.models.video import Video
from app.models.student import Student
from app.models.track import Track
from app.models.recognition import StudentRecognitionEvent
from app.tasks.video_tasks import process_video


@pytest.fixture(scope="module", autouse=True)
def setup_test_db():
    os.makedirs(os.path.dirname(TEST_DB_PATH), exist_ok=True)
    async def _init():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("PRAGMA foreign_keys=ON"))
    asyncio.run(_init())
    yield


def test_uuid_bind_param_conversions():
    """Verify SqliteCompatibleUUID binds uuid.UUID, 32-char hex, and 36-char hyphenated strings canonically."""
    custom_type = SqliteCompatibleUUID()
    
    test_uuid = uuid.uuid4()
    hex_str = test_uuid.hex
    canon_str = str(test_uuid)
    
    assert custom_type.process_bind_param(test_uuid, None) == canon_str
    assert custom_type.process_bind_param(hex_str, None) == canon_str
    assert custom_type.process_bind_param(canon_str, None) == canon_str
    assert custom_type.process_bind_param(None, None) is None
    
    # Result value conversion to uuid.UUID
    assert custom_type.process_result_value(canon_str, None) == test_uuid
    assert custom_type.process_result_value(hex_str, None) == test_uuid
    assert custom_type.process_result_value(None, None) is None


def test_student_recognition_foreign_key_with_legacy_and_canonical_uuids():
    """
    Test that StudentRecognitionEvent can be inserted referencing both
    canonical 36-character UUID and legacy 32-character hex UUID, resolving
    correctly under enforced PRAGMA foreign_keys=ON.
    """
    async def _run():
        student_uuid = uuid.uuid4()
        user_uuid = uuid.uuid4()
        cam_uuid = uuid.uuid4()
        vid_uuid = uuid.uuid4()
        track_uuid = uuid.uuid4()

        async with SessionLocal() as db:
            # Create prerequisite user, camera, video, track, and student
            user = User(
                id=user_uuid,
                email=f"phase_b_{uuid.uuid4().hex[:6]}@test.com",
                hashed_password="hash",
                is_active=True,
                role="admin"
            )
            cam = Camera(
                id=cam_uuid,
                name=f"Phase B Cam {uuid.uuid4().hex[:4]}",
                building="Tech Block",
                floor=1,
                location="Gate 1",
                direction="North",
                resolution="1080p",
                status="active"
            )
            vid = Video(
                id=vid_uuid,
                title="Phase B Video",
                filename="test.mp4",
                original_filename="test.mp4",
                file_path="storage/test.mp4",
                uploaded_by=user_uuid,
                camera_id=str(cam_uuid),
                status="completed"
            )
            trk = Track(
                id=track_uuid,
                video_id=vid_uuid,
                tracker_id=1,
                object_class="person",
                start_time=0.0,
                end_time=5.0
            )
            student = Student(
                id=student_uuid,
                university_roll_number=f"ROLL_{uuid.uuid4().hex[:6]}",
                name="Alice Test",
                department="Computer Science",
                programme="B.Tech",
                year=3,
                semester=5,
                section="A",
                email=f"alice_{uuid.uuid4().hex[:6]}@univ.edu"
            )
            db.add_all([user, cam, vid, trk, student])
            await db.commit()

        # 1. Insert recognition event referencing student with canonical UUID object
        async with SessionLocal() as db:
            rec_event_1 = StudentRecognitionEvent(
                id=uuid.uuid4(),
                track_id=track_uuid,
                student_id=student_uuid,  # uuid.UUID
                video_id=vid_uuid,
                timestamp=datetime.now(timezone.utc),
                similarity_score=0.88,
                confidence="high",
                camera_id=str(cam_uuid)
            )
            db.add(rec_event_1)
            await db.commit()

            # Verify query joins and resolves student
            loaded = (await db.execute(
                select(StudentRecognitionEvent).where(StudentRecognitionEvent.id == rec_event_1.id)
            )).scalars().first()
            assert loaded is not None
            assert loaded.student_id == student_uuid

        # 2. Insert recognition event referencing student with 32-char hex string
        rec_event_2_id = uuid.uuid4()
        async with SessionLocal() as db:
            rec_event_2 = StudentRecognitionEvent(
                id=rec_event_2_id,
                track_id=track_uuid,
                student_id=student_uuid.hex,  # 32-char hex string
                video_id=vid_uuid,
                timestamp=datetime.now(timezone.utc),
                similarity_score=0.75,
                confidence="medium",
                camera_id=str(cam_uuid)
            )
            db.add(rec_event_2)
            await db.commit()

        # In a separate clean session, verify DB persistence and UUID conversion
        async with SessionLocal() as db:
            loaded = (await db.execute(
                select(StudentRecognitionEvent).where(StudentRecognitionEvent.id == rec_event_2_id)
            )).scalars().first()
            assert loaded is not None
            assert loaded.student_id == student_uuid
            # Also verify join with Student relationship succeeds under foreign key
            std = (await db.execute(
                select(Student).where(Student.id == loaded.student_id)
            )).scalars().first()
            assert std is not None
            assert std.id == student_uuid

    asyncio.run(_run())


def test_invalid_student_foreign_key_rejected():
    """Verify PRAGMA foreign_keys=ON strictly rejects invalid student parent references."""
    async def _run():
        fake_student_id = uuid.uuid4()
        vid_uuid = uuid.uuid4()
        user_uuid = uuid.uuid4()
        track_uuid = uuid.uuid4()

        async with SessionLocal() as db:
            user = User(
                id=user_uuid,
                email=f"fake_{uuid.uuid4().hex[:6]}@test.com",
                hashed_password="hash",
                is_active=True,
                role="admin"
            )
            vid = Video(
                id=vid_uuid,
                title="Fake Video",
                filename="fake.mp4",
                original_filename="fake.mp4",
                file_path="storage/fake.mp4",
                uploaded_by=user_uuid,
                status="completed"
            )
            trk = Track(
                id=track_uuid,
                video_id=vid_uuid,
                tracker_id=2,
                object_class="person",
                start_time=0.0,
                end_time=5.0
            )
            db.add_all([user, vid, trk])
            await db.commit()

            rec_invalid = StudentRecognitionEvent(
                id=uuid.uuid4(),
                track_id=track_uuid,
                student_id=fake_student_id,  # DOES NOT EXIST
                video_id=vid_uuid,
                timestamp=datetime.now(timezone.utc),
                similarity_score=0.90,
                confidence="high"
            )
            db.add(rec_invalid)
            with pytest.raises(IntegrityError):
                await db.commit()

    asyncio.run(_run())


def test_non_blocking_eager_video_dispatch():
    """
    Verify that in eager mode, process_video.delay() dispatches to the background
    executor and returns in < 100ms, without blocking the calling thread.
    """
    vid_id = uuid.uuid4()
    user_uuid = uuid.uuid4()

    async def _setup():
        async with SessionLocal() as db:
            user = User(
                id=user_uuid,
                email=f"dispatch_{uuid.uuid4().hex[:6]}@test.com",
                hashed_password="hash",
                is_active=True,
                role="admin"
            )
            vid = Video(
                id=vid_id,
                title="Async Dispatch Video",
                filename="dispatch.mp4",
                original_filename="dispatch.mp4",
                file_path="storage/dispatch.mp4",
                uploaded_by=user_uuid,
                status="queued"
            )
            db.add_all([user, vid])
            await db.commit()

    asyncio.run(_setup())

    # Mock the heavy orchestrator.execute to simulate 0.5s of processing work
    async def mock_execute(video_id):
        await asyncio.sleep(0.5)

    with patch("app.tasks.video_tasks.VideoProcessingOrchestrator.execute", side_effect=mock_execute):
        start_t = time.time()
        # Call .delay()
        process_video.delay(str(vid_id))
        elapsed_delay = time.time() - start_t
        
        # Must return almost instantaneously (well under 100ms)
        assert elapsed_delay < 0.10, f"process_video.delay took {elapsed_delay:.4f}s, expected < 0.10s"

        # Check that video transitioned to processing in background
        time.sleep(0.15)
        async def _check():
            async with SessionLocal() as db:
                video = (await db.execute(select(Video).where(Video.id == vid_id))).scalars().first()
                assert video.status in ("processing", "completed")

        asyncio.run(_check())

        # Wait for simulated processing to finish
        time.sleep(0.5)


def test_processing_failure_handling():
    """Verify that exceptions in background task properly mark video status to failed with error message."""
    vid_id = uuid.uuid4()
    user_uuid = uuid.uuid4()

    async def _setup():
        async with SessionLocal() as db:
            user = User(
                id=user_uuid,
                email=f"fail_{uuid.uuid4().hex[:6]}@test.com",
                hashed_password="hash",
                is_active=True,
                role="admin"
            )
            vid = Video(
                id=vid_id,
                title="Failing Video",
                filename="fail.mp4",
                original_filename="fail.mp4",
                file_path="storage/fail.mp4",
                uploaded_by=user_uuid,
                status="queued"
            )
            db.add_all([user, vid])
            await db.commit()

    asyncio.run(_setup())

    async def mock_fail_execute(video_id):
        raise RuntimeError("Simulated Pipeline Failure: Corrupted video stream")

    with patch("app.tasks.video_tasks.VideoProcessingOrchestrator.execute", side_effect=mock_fail_execute):
        process_video.delay(str(vid_id))
        time.sleep(0.3)  # Allow background thread to process and catch exception

        async def _check():
            async with SessionLocal() as db:
                video = (await db.execute(select(Video).where(Video.id == vid_id))).scalars().first()
                assert video.status == "failed"
                assert video.current_stage == "Failed"
                assert "Simulated Pipeline Failure" in (video.error_message or "")

        asyncio.run(_check())


def test_synchronous_apply_still_works_for_tests():
    """Verify that process_video.apply() executes synchronously for direct test suites."""
    vid_id = uuid.uuid4()
    user_uuid = uuid.uuid4()

    async def _setup():
        async with SessionLocal() as db:
            user = User(
                id=user_uuid,
                email=f"apply_{uuid.uuid4().hex[:6]}@test.com",
                hashed_password="hash",
                is_active=True,
                role="admin"
            )
            vid = Video(
                id=vid_id,
                title="Apply Video",
                filename="apply.mp4",
                original_filename="apply.mp4",
                file_path="storage/apply.mp4",
                uploaded_by=user_uuid,
                status="queued"
            )
            db.add_all([user, vid])
            await db.commit()

    asyncio.run(_setup())

    # Synchronous permanent error test (like test_celery_permanent_error_no_retry)
    with patch("app.tasks.video_tasks.VideoProcessingOrchestrator.execute", side_effect=FileNotFoundError("Missing video file")):
        process_video.apply(args=[str(vid_id)])

        async def _check():
            async with SessionLocal() as db:
                video = (await db.execute(select(Video).where(Video.id == vid_id))).scalars().first()
                assert video.status == "failed"
                assert "Missing video file" in (video.error_message or "")

        asyncio.run(_check())
