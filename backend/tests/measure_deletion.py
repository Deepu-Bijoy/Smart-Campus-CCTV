import time
import os
import sys
import uuid
import asyncio

backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.db.session import SessionLocal
from app.models.camera import Camera
from app.models.video import Video
from app.models.student import Student
from app.models.user import User
from app.core import security
from sqlalchemy import select
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

async def measure():
    async with SessionLocal() as db:
        res = await db.execute(select(User).filter(User.is_active == True, User.role == "admin"))
        user = res.scalars().first()
        token = security.create_access_token(user.id)
        headers = {"Authorization": f"Bearer {token}"}

    # 1. Student deletion measurement
    student_id = uuid.uuid4()
    async with SessionLocal() as db:
        s = Student(
            id=student_id,
            university_roll_number=f"MEAS-{uuid.uuid4().hex[:6]}",
            name="Measurement Student",
            department="CSE",
            programme="B.Tech",
            year=1,
            semester=1,
            section="A",
            email=f"meas-{uuid.uuid4().hex[:6]}@campus.edu",
            embedding_generated=False
        )
        db.add(s)
        await db.commit()

    t0 = time.time()
    res_s = client.delete(f"/api/v1/students/{student_id}", headers=headers)
    t1 = time.time()
    s_ms = (t1 - t0) * 1000
    print(f"Student DELETE: status={res_s.status_code}, time={s_ms:.2f}ms")

    # 2. Completed Video deletion measurement
    camera_id = uuid.uuid4()
    video_id = uuid.uuid4()
    async with SessionLocal() as db:
        c = Camera(
            id=camera_id,
            name="Meas-Cam",
            building="B",
            floor=1,
            location="L",
            direction="North",
            resolution="1080p",
            status="active"
        )
        db.add(c)
        v = Video(
            id=video_id,
            title="Meas Video",
            filename="meas.mp4",
            original_filename="meas.mp4",
            file_path="storage/meas.mp4",
            status="completed",
            camera_id=camera_id,
            uploaded_by=user.id
        )
        db.add(v)
        await db.commit()

    t2 = time.time()
    res_v = client.delete(f"/api/v1/videos/{video_id}", headers=headers)
    t3 = time.time()
    v_ms = (t3 - t2) * 1000
    print(f"Completed Video DELETE: status={res_v.status_code}, time={v_ms:.2f}ms")

    # 3. Processing Video deletion measurement (checking cancellation & cleanup)
    video_proc_id = uuid.uuid4()
    async with SessionLocal() as db:
        v_proc = Video(
            id=video_proc_id,
            title="Meas Proc Video",
            filename="meas_proc.mp4",
            original_filename="meas_proc.mp4",
            file_path="storage/meas_proc.mp4",
            status="processing",
            current_stage="Object Detection",
            progress_percentage=45,
            camera_id=camera_id,
            uploaded_by=user.id
        )
        db.add(v_proc)
        await db.commit()

    t4 = time.time()
    res_vp = client.delete(f"/api/v1/videos/{video_proc_id}", headers=headers)
    t5 = time.time()
    vp_ms = (t5 - t4) * 1000
    print(f"Processing Video DELETE: status={res_vp.status_code}, time={vp_ms:.2f}ms")

    # Cleanup camera
    async with SessionLocal() as db:
        cam_row = (await db.execute(select(Camera).filter(Camera.id == camera_id))).scalars().first()
        if cam_row:
            await db.delete(cam_row)
            await db.commit()

if __name__ == "__main__":
    asyncio.run(measure())
