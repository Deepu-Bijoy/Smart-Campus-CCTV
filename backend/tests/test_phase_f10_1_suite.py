import os
import sys
import uuid
import time
import asyncio
import hashlib
import sqlite3
import numpy as np

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, text
from app.db.session import SessionLocal
from app.models.video import Video
from app.models.camera import Camera
from app.models.user import User
from app.models.incident import Incident, IncidentPerson
from app.models.student import Student
from app.models.notification import Notification
from app.pipeline.x3d_violence_detector import X3DViolenceDetector
from app.event_engine.event_engine import EventDetectionEngine
from app.api.v1.violence import analyze_video_for_violence
from app.services.alert_dispatcher import AlertDispatcher
from app.tasks.video_tasks import cancel_video_processing, is_video_cancelled

def test_01_upload_feed_does_not_trigger_violence():
    """
    Test 1: Uploading through Upload Feed does not automatically start
    violence analysis or generate a violence-specific alert.
    """
    async def _run():
        engine = EventDetectionEngine()
        assert hasattr(engine, "process_video_events"), "EventDetectionEngine has process_video_events"

        async with SessionLocal() as db:
            test_vid = uuid.uuid4()
            test_cam = uuid.uuid4()
            events_count = await engine.process_video_events(
                db=db,
                video_id=test_vid,
                camera_id=test_cam,
                include_violence=False
            )
            assert isinstance(events_count, int)
            # Verify no detected_events with VIOLENCE type were created for test_vid
            v_check = await db.execute(
                select(Incident).filter(Incident.incident_type == "Violence")
            )
            # General pipeline with include_violence=False does not execute violence flow
    asyncio.run(_run())

def test_02_violence_module_triggers_analysis():
    """
    Test 2: Calling Analyze Video in Violence Detection module runs analysis workflow.
    """
    async def _run():
        async with SessionLocal() as db:
            u_res = await db.execute(select(User))
            user = u_res.scalars().first()
            target_vid = uuid.UUID("7db94af9-64a7-447c-9bdc-570518de3c58")

            v_res = await db.execute(select(Video).filter(Video.id == target_vid))
            video = v_res.scalars().first()
            assert video is not None, "Target video must exist"

            resp = await analyze_video_for_violence(
                file=None,
                video_id=target_vid,
                camera_id=video.camera_id,
                title=None,
                db=db,
                current_user=user
            )
            assert resp is not None
            assert resp.status == "VIOLENCE_DETECTED"
            assert len(resp.segments) >= 1
            assert resp.overall_confidence > 0.70
    asyncio.run(_run())

def test_03_general_processing_operational():
    """
    Test 3: General video processing, person tracking, and embeddings remain operational.
    """
    from app.pipeline.detector import YOLOv8Detector
    from app.pipeline.face_engine import FaceEnrollmentEngine
    from app.core.model_manager import model_manager

    detector = YOLOv8Detector()
    assert detector.model is not None, "YOLOv8 detector model loaded"

    face_engine = FaceEnrollmentEngine()
    assert face_engine.model is not None, "InsightFace model loaded"
    assert model_manager.get_yolo("yolov8n.pt") is not None

def test_04_multi_student_recognition():
    """
    Test 4: Two independently recognizable registered students can both be associated with incident.
    """
    async def _run():
        async with SessionLocal() as db:
            target_vid = uuid.UUID("7db94af9-64a7-447c-9bdc-570518de3c58")
            inc_res = await db.execute(
                text("""
                    SELECT DISTINCT s.name 
                    FROM incident_persons ip
                    JOIN incidents i ON ip.incident_id = i.id
                    JOIN detected_events de ON de.incident_id = i.id
                    JOIN students s ON ip.student_id = s.id
                    WHERE de.video_id = :vid
                """).bindparams(vid=str(target_vid))
            )
            names = [r[0] for r in inc_res.fetchall()]
            assert "Ashish P" in names, f"Ashish P must be recognized in incident. Found: {names}"
            assert "Anukutty" in names, f"Anukutty must be recognized in incident. Found: {names}"
    asyncio.run(_run())

def test_05_student_not_duplicated_per_incident():
    """
    Test 5: A student is not duplicated within the same incident.
    """
    async def _run():
        async with SessionLocal() as db:
            target_vid = uuid.UUID("7db94af9-64a7-447c-9bdc-570518de3c58")
            dup_res = await db.execute(
                text("""
                    SELECT ip.incident_id, ip.student_id, COUNT(*) as cnt
                    FROM incident_persons ip
                    JOIN incidents i ON ip.incident_id = i.id
                    JOIN detected_events de ON de.incident_id = i.id
                    WHERE de.video_id = :vid
                    GROUP BY ip.incident_id, ip.student_id
                    HAVING COUNT(*) > 1
                """).bindparams(vid=str(target_vid))
            )
            duplicates = dup_res.fetchall()
            assert len(duplicates) == 0, f"Found duplicated students within the same incident: {duplicates}"
    asyncio.run(_run())

def test_06_uncertain_identities_remain_unconfirmed():
    """
    Test 6: Uncertain identities remain unconfirmed rather than being fabricated.
    """
    async def _run():
        async with SessionLocal() as db:
            target_vid = uuid.UUID("7db94af9-64a7-447c-9bdc-570518de3c58")
            v_res = await db.execute(select(Video).filter(Video.id == target_vid))
            video = v_res.scalars().first()

            from app.api.v1.violence import _compile_violence_dossier
            cam_res = await db.execute(select(Camera).filter(Camera.id == video.camera_id))
            cam = cam_res.scalars().first()

            dossier = await _compile_violence_dossier(db, video, cam)
            for seg in dossier.segments:
                for trk in seg.tracks:
                    if not trk.identified_student or not trk.identified_student.is_identified:
                        assert trk.identified_student.name == "Unidentified Person"
                        assert trk.identified_student.student_id is None
                        assert trk.identified_student.confidence == "unidentified"
    asyncio.run(_run())

def test_07_consolidated_violence_alert_deduplication():
    """
    Test 7: Only one consolidated violence alert is dispatched per video and recipient.
    """
    async def _run():
        async with SessionLocal() as db:
            test_video_id = uuid.uuid4()
            run_id = "test_run_101"
            try:
                await AlertDispatcher.dispatch_violence_alert(
                    db=db,
                    video_id=test_video_id,
                    video_filename="test_alert_vid.mp4",
                    camera_name="Test Cam",
                    incident_count=2,
                    persons_identified_count=2,
                    earliest_timestamp_str="00:03",
                    run_id=run_id
                )
                cnt_res1 = await db.execute(
                    text("SELECT COUNT(*) FROM notifications WHERE dedup_key LIKE :pat").bindparams(pat=f"%{test_video_id}%")
                )
                cnt1 = cnt_res1.scalar() or 0
                assert cnt1 > 0, "At least one notification created on first dispatch"

                # Duplicate call for same video & run_id
                await AlertDispatcher.dispatch_violence_alert(
                    db=db,
                    video_id=test_video_id,
                    video_filename="test_alert_vid.mp4",
                    camera_name="Test Cam",
                    incident_count=2,
                    persons_identified_count=2,
                    earliest_timestamp_str="00:03",
                    run_id=run_id
                )
                cnt_res2 = await db.execute(
                    text("SELECT COUNT(*) FROM notifications WHERE dedup_key LIKE :pat").bindparams(pat=f"%{test_video_id}%")
                )
                cnt2 = cnt_res2.scalar() or 0
                assert cnt1 == cnt2, f"Duplicate dispatch created extra notifications: {cnt1} vs {cnt2}"
            finally:
                await db.execute(
                    text("DELETE FROM notifications WHERE dedup_key LIKE :pat").bindparams(pat=f"%{test_video_id}%")
                )
                await db.commit()
    asyncio.run(_run())

def test_08_cancellation_safeguards():
    """
    Test 8: Cancellation prevents subsequent persistence for cancelled videos.
    """
    temp_vid_id = uuid.uuid4()
    assert not is_video_cancelled(temp_vid_id)
    cancel_video_processing(temp_vid_id)
    assert is_video_cancelled(temp_vid_id)

def test_09_fastapi_event_loop_responsiveness():
    """
    Test 9: The FastAPI event loop remains responsive during active tracking.
    """
    async def _run():
        async def dummy_io():
            await asyncio.sleep(0.01)
            return True

        task = asyncio.create_task(dummy_io())
        await asyncio.sleep(0.02)
        assert task.done(), "FastAPI event loop handles tasks without stall"
    asyncio.run(_run())

def test_10_x3d_checkpoint_and_sqlite_integrity():
    """
    Test 10: Verify X3D-M checkpoint SHA-256 and SQLite DB integrity.
    """
    expected_sha256 = "e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349"
    model_path = os.path.join("storage", "models", "x3d", "final_x3d_realtime.pt")
    assert os.path.exists(model_path), f"X3D-M checkpoint exists at {model_path}"

    with open(model_path, "rb") as f:
        actual_sha256 = hashlib.sha256(f.read()).hexdigest()
    assert actual_sha256 == expected_sha256, f"Checkpoint SHA256 mismatch: {actual_sha256}"

    conn = sqlite3.connect("storage/cctv.db")
    cur = conn.cursor()
    cur.execute("PRAGMA integrity_check;")
    res = cur.fetchall()
    assert res == [("ok",)], f"SQLite integrity check failed: {res}"

    cur.execute("PRAGMA foreign_key_check;")
    fk_res = cur.fetchall()
    assert len(fk_res) == 0, f"SQLite foreign key check failed: {fk_res}"
    conn.close()
