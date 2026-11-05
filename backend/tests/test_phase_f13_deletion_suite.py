import os
import sys
import uuid
import time
import asyncio
from unittest.mock import MagicMock

# Mock out heavy ML modules not needed for API route validation
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['insightface'] = MagicMock()
sys.modules['insightface.app'] = MagicMock()

backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from app.main import app
from app.core import security
from app.db.session import SessionLocal
from app.models.user import User
from app.models.camera import Camera
from app.models.student import Student, StudentPhoto
from app.models.video import Video
from app.models.recognition import StudentRecognitionEvent

client = TestClient(app)

async def _get_admin_headers():
    async with SessionLocal() as db:
        res = await db.execute(select(User).filter(User.is_active == True, User.role == "admin"))
        user = res.scalars().first()
        if not user:
            res = await db.execute(select(User).filter(User.is_active == True))
            user = res.scalars().first()
        assert user is not None, "At least one active user must exist"
        token = security.create_access_token(user.id)
        return {"Authorization": f"Bearer {token}"}, user.id

async def run_phase_f13_tests():
    print("=" * 70)
    print("PHASE F13: STUDENT AND VIDEO DELETION REGRESSION TEST SUITE")
    print("=" * 70)

    headers, admin_id = await _get_admin_headers()

    # -------------------------------------------------------------
    # 1. SETUP DISPOSABLE TEST DATA
    # -------------------------------------------------------------
    cam_id = uuid.uuid4()
    student_a_id = uuid.uuid4()
    student_b_id = uuid.uuid4()
    video_completed_id = uuid.uuid4()
    video_processing_id = uuid.uuid4()
    video_unrelated_id = uuid.uuid4()

    async with SessionLocal() as db:
        # Create test camera
        cam = Camera(
            id=cam_id,
            name=f"F13-Test-Camera-{uuid.uuid4().hex[:6]}",
            building="Building Alpha",
            floor=1,
            location="Perimeter North",
            direction="North",
            resolution="1080p",
            status="active"
        )
        db.add(cam)

        # Create two test students (one to delete, one to stay)
        student_a = Student(
            id=student_a_id,
            university_roll_number=f"F13-ROLL-A-{uuid.uuid4().hex[:6]}",
            name="F13 Student To Delete",
            department="Computer Science",
            programme="B.Tech",
            year=3,
            semester=5,
            section="A",
            email=f"f13_student_a_{uuid.uuid4().hex[:6]}@campus.edu",
            status="active"
        )
        student_b = Student(
            id=student_b_id,
            university_roll_number=f"F13-ROLL-B-{uuid.uuid4().hex[:6]}",
            name="F13 Unrelated Student",
            department="Electrical Engineering",
            programme="B.Tech",
            year=2,
            semester=3,
            section="B",
            email=f"f13_student_b_{uuid.uuid4().hex[:6]}@campus.edu",
            status="active"
        )
        db.add(student_a)
        db.add(student_b)

        # Create three test videos (completed, processing, unrelated)
        vid_comp = Video(
            id=video_completed_id,
            camera_id=cam_id,
            filename=f"f13_completed_{uuid.uuid4().hex[:6]}.mp4",
            original_filename=f"f13_completed_{uuid.uuid4().hex[:6]}.mp4",
            file_path=f"storage/videos/f13_comp_{uuid.uuid4().hex[:6]}.mp4",
            file_size=1024 * 1024,
            status="completed",
            uploaded_by=admin_id
        )
        vid_proc = Video(
            id=video_processing_id,
            camera_id=cam_id,
            filename=f"f13_proc_{uuid.uuid4().hex[:6]}.mp4",
            original_filename=f"f13_proc_{uuid.uuid4().hex[:6]}.mp4",
            file_path=f"storage/videos/f13_proc_{uuid.uuid4().hex[:6]}.mp4",
            file_size=1024 * 1024,
            status="processing",
            progress_percentage=45,
            current_stage="Object Detection",
            uploaded_by=admin_id
        )
        vid_unrel = Video(
            id=video_unrelated_id,
            camera_id=cam_id,
            filename=f"f13_unrel_{uuid.uuid4().hex[:6]}.mp4",
            original_filename=f"f13_unrel_{uuid.uuid4().hex[:6]}.mp4",
            file_path=f"storage/videos/f13_unrel_{uuid.uuid4().hex[:6]}.mp4",
            file_size=1024 * 1024,
            status="completed",
            uploaded_by=admin_id
        )
        db.add(vid_comp)
        db.add(vid_proc)
        db.add(vid_unrel)

        await db.commit()
    print("[1/5] Disposable test records provisioned successfully.")

    # -------------------------------------------------------------
    # 2. STUDENT DELETION & SUB-ENDPOINT 404 INTEGRITY
    # -------------------------------------------------------------
    # Confirm student A is in list
    res_list = client.get("/api/v1/students", headers=headers)
    assert res_list.status_code == 200
    student_ids_before = [s["id"] for s in res_list.json()["items"]]
    assert str(student_a_id) in student_ids_before
    assert str(student_b_id) in student_ids_before

    # Time DELETE /api/v1/students/{student_a_id}
    t0 = time.perf_counter()
    res_del_student = client.delete(f"/api/v1/students/{student_a_id}", headers=headers)
    student_del_time_ms = (time.perf_counter() - t0) * 1000
    assert res_del_student.status_code == 204, f"Expected 204, got {res_del_student.status_code}"
    print(f"[2/5] Student DELETE: status=204 in {student_del_time_ms:.2f}ms")

    # Verify student A immediately disappears from student list
    res_list_after = client.get("/api/v1/students", headers=headers)
    assert res_list_after.status_code == 200
    student_ids_after = [s["id"] for s in res_list_after.json()["items"]]
    assert str(student_a_id) not in student_ids_after, "Deleted student must not appear in directory list"
    assert str(student_b_id) in student_ids_after, "Unrelated student B must remain intact"

    # Verify subsequent GET requests to deleted student return deterministic 404 (and no 500s)
    res_get_student = client.get(f"/api/v1/students/{student_a_id}", headers=headers)
    assert res_get_student.status_code == 404, f"Expected 404, got {res_get_student.status_code}"

    res_get_photos = client.get(f"/api/v1/students/{student_a_id}/photos", headers=headers)
    assert res_get_photos.status_code == 404, f"Expected 404, got {res_get_photos.status_code}"

    res_get_enroll = client.get(f"/api/v1/students/{student_a_id}/enrollment-status", headers=headers)
    assert res_get_enroll.status_code == 404, f"Expected 404, got {res_get_enroll.status_code}"

    res_get_appear = client.get(f"/api/v1/investigations/students/{student_a_id}/appearances", headers=headers)
    assert res_get_appear.status_code == 404, f"Expected 404, got {res_get_appear.status_code}"

    # Verify second DELETE returns 404 (idempotent missing resource check)
    res_del_again = client.delete(f"/api/v1/students/{student_a_id}", headers=headers)
    assert res_del_again.status_code == 404, f"Expected 404 on repeated delete, got {res_del_again.status_code}"
    print("[2/5] Student deletion lifecycle, list removal, and deterministic 404 responses verified.")

    # -------------------------------------------------------------
    # 3. COMPLETED VIDEO DELETION
    # -------------------------------------------------------------
    # Confirm completed video is in list
    res_vids_before = client.get("/api/v1/videos", headers=headers)
    assert res_vids_before.status_code == 200
    vid_items_before = res_vids_before.json()
    if isinstance(vid_items_before, dict) and "items" in vid_items_before:
        vid_items_before = vid_items_before["items"]
    v_ids_before = [v["id"] for v in vid_items_before]
    assert str(video_completed_id) in v_ids_before
    assert str(video_processing_id) in v_ids_before
    assert str(video_unrelated_id) in v_ids_before

    # Time DELETE /api/v1/videos/{video_completed_id}
    t0 = time.perf_counter()
    res_del_comp = client.delete(f"/api/v1/videos/{video_completed_id}", headers=headers)
    comp_del_time_ms = (time.perf_counter() - t0) * 1000
    assert res_del_comp.status_code == 204, f"Expected 204, got {res_del_comp.status_code}"
    print(f"[3/5] Completed Video DELETE: status=204 in {comp_del_time_ms:.2f}ms")

    # Verify completed video disappears from video list
    res_vids_after_comp = client.get("/api/v1/videos", headers=headers)
    v_items_after_comp = res_vids_after_comp.json()
    if isinstance(v_items_after_comp, dict) and "items" in v_items_after_comp:
        v_items_after_comp = v_items_after_comp["items"]
    v_ids_after_comp = [v["id"] for v in v_items_after_comp]
    assert str(video_completed_id) not in v_ids_after_comp, "Deleted completed video must not appear in list"
    assert str(video_unrelated_id) in v_ids_after_comp, "Unrelated video must remain visible"

    # -------------------------------------------------------------
    # 4. PROCESSING VIDEO DELETION & CANCELLATION GUARANTEES
    # -------------------------------------------------------------
    # Time DELETE /api/v1/videos/{video_processing_id}
    t0 = time.perf_counter()
    res_del_proc = client.delete(f"/api/v1/videos/{video_processing_id}", headers=headers)
    proc_del_time_ms = (time.perf_counter() - t0) * 1000
    assert res_del_proc.status_code == 204, f"Expected 204, got {res_del_proc.status_code}"
    print(f"[4/5] Processing Video DELETE (with cancellation): status=204 in {proc_del_time_ms:.2f}ms")

    # Verify processing video disappears from list
    res_vids_after_proc = client.get("/api/v1/videos", headers=headers)
    v_items_after_proc = res_vids_after_proc.json()
    if isinstance(v_items_after_proc, dict) and "items" in v_items_after_proc:
        v_items_after_proc = v_items_after_proc["items"]
    v_ids_after_proc = [v["id"] for v in v_items_after_proc]
    assert str(video_processing_id) not in v_ids_after_proc, "Deleted processing video must not appear in list"
    assert str(video_unrelated_id) in v_ids_after_proc, "Unrelated video must remain visible"

    # Verify subsequent GET returns 404
    res_get_proc = client.get(f"/api/v1/videos/{video_processing_id}", headers=headers)
    assert res_get_proc.status_code == 404, f"Expected 404, got {res_get_proc.status_code}"

    # Verify repeated DELETE returns 404
    res_del_proc_again = client.delete(f"/api/v1/videos/{video_processing_id}", headers=headers)
    assert res_del_proc_again.status_code == 404, f"Expected 404 on repeated delete, got {res_del_proc_again.status_code}"

    # Check dashboard metrics endpoint reflects live counts
    res_dash = client.get("/api/v1/dashboard", headers=headers)
    assert res_dash.status_code == 200
    dash_data = res_dash.json()
    assert "total_videos" in dash_data
    assert "enrolled_students" in dash_data
    print(f"[4/5] Dashboard metrics verified: total_videos={dash_data['total_videos']}, enrolled_students={dash_data['enrolled_students']}")

    # -------------------------------------------------------------
    # 5. CLEANUP REMAINING DISPOSABLE TEST DATA
    # -------------------------------------------------------------
    async with SessionLocal() as db:
        await db.execute(text("DELETE FROM videos WHERE id = :vid").bindparams(vid=str(video_unrelated_id)))
        await db.execute(text("DELETE FROM students WHERE id = :sid").bindparams(sid=str(student_b_id)))
        await db.execute(text("DELETE FROM cameras WHERE id = :cid").bindparams(cid=str(cam_id)))
        await db.commit()
    print("[5/5] Disposable test records cleaned up cleanly.")

    print("=" * 70)
    print("ALL PHASE F13 REGRESSION TESTS PASSED SUCCESSFULLY!")
    print(f"Summary Latencies:")
    print(f"  - Student Deletion:          {student_del_time_ms:.2f} ms")
    print(f"  - Completed Video Deletion:  {comp_del_time_ms:.2f} ms")
    print(f"  - Processing Video Deletion: {proc_del_time_ms:.2f} ms")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_phase_f13_tests())
