import asyncio
import os
import sys
import uuid
import cv2
import numpy as np
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Configure test environment
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_student_id.db"

# Mock out heavy models that are not needed for unit logic
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.models.user import User
from app.models.video import Video
from app.models.camera import Camera
from app.models.student import Student, StudentPhoto
from app.models.track import Track, Detection, PersonReid
from app.models.incident import Incident, DetectedEvent, Evidence, IncidentPerson
from app.models.recognition import StudentRecognitionEvent
from app.services.student_identifier import StudentIdentifier
from app.api.v1.violence import _compile_violence_dossier
from app.schemas.violence import InvolvedStudentCard

client = TestClient(app)

def create_synthetic_mp4(filepath: str, duration_sec: float = 10.0, fps: float = 10.0):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    total_frames = int(duration_sec * fps)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filepath, fourcc, fps, (320, 240))
    for i in range(total_frames):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.rectangle(frame, (80, 50), (140, 200), (200, 200, 200), -1)
        out.write(frame)
    out.release()

def create_dummy_crop(filepath: str, face_type: str = "frontal"):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    img = np.zeros((160, 100, 3), dtype=np.uint8)
    if face_type == "frontal":
        # Draw clear oval representing frontal face
        cv2.circle(img, (50, 45), 25, (220, 220, 220), -1)
        cv2.circle(img, (40, 40), 4, (40, 40, 40), -1)
        cv2.circle(img, (60, 40), 4, (40, 40, 40), -1)
    elif face_type == "side_profile":
        # Draw side face profile
        cv2.ellipse(img, (40, 45), (15, 25), 20, 0, 360, (200, 200, 200), -1)
    elif face_type == "blurry":
        # Blurry noise
        cv2.circle(img, (50, 45), 25, (120, 120, 120), -1)
        img = cv2.GaussianBlur(img, (25, 25), 10.0)
    elif face_type == "no_face":
        # Person from behind (dark hair / hoodie only)
        cv2.circle(img, (50, 45), 25, (30, 30, 30), -1)
    cv2.imwrite(filepath, img)

async def init_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

def run_student_identification_tests():
    print("\n=======================================================")
    print("  RUNNING VIOLENCE STUDENT IDENTIFICATION TEST SUITE")
    print("=======================================================")
    asyncio.run(init_test_db())

    storage_dir = settings.STORAGE_DIR
    os.makedirs(os.path.join(storage_dir, "crops"), exist_ok=True)
    os.makedirs(os.path.join(storage_dir, "photos"), exist_ok=True)
    os.makedirs(storage_dir, exist_ok=True)

    test_video_path = os.path.join(storage_dir, "test_student_id_source.mp4")
    create_synthetic_mp4(test_video_path, duration_sec=10.0, fps=10.0)

    # 1. Seed database with registered students
    student_a_id = uuid.uuid4()
    student_b_id = uuid.uuid4()
    user_id = uuid.uuid4()
    cam_id = uuid.uuid4()
    base_time = datetime.now(timezone.utc)

    async def seed_students():
        async with SessionLocal() as db:
            user = User(
                id=user_id,
                email="director@smartcampus.edu",
                hashed_password="fakepassword",
                role="admin"
            )
            db.add(user)

            cam = Camera(
                id=cam_id,
                name="Library Lawn Gate",
                building="Central Library",
                floor="Ground",
                location="Lawn",
                direction="East",
                resolution="1920x1080",
                status="active"
            )
            db.add(cam)

            # Registered Student A
            s_a = Student(
                id=student_a_id,
                university_roll_number="CS2024001",
                name="Aarav Sharma",
                department="Computer Science & Engineering",
                programme="B.Tech CS",
                year=3,
                semester=5,
                section="Section A",
                email="aarav.sharma@smartcampus.edu",
                status="active",
                embedding_generated=True
            )
            db.add(s_a)

            photo_a_path = os.path.join(storage_dir, "photos", "student_a_front.jpg")
            create_dummy_crop(photo_a_path, "frontal")
            db.add(StudentPhoto(
                id=uuid.uuid4(),
                student_id=student_a_id,
                photo_path=photo_a_path,
                view="front",
                file_size=os.path.getsize(photo_a_path),
                mime_type="image/jpeg",
                md5_hash="hash_a"
            ))

            # Registered Student B
            s_b = Student(
                id=student_b_id,
                university_roll_number="EC2024089",
                name="Priya Patel",
                department="Electronics & Communication",
                programme="B.Tech ECE",
                year=2,
                semester=3,
                section="Section B",
                email="priya.patel@smartcampus.edu",
                status="active",
                embedding_generated=True
            )
            db.add(s_b)

            photo_b_path = os.path.join(storage_dir, "photos", "student_b_front.jpg")
            create_dummy_crop(photo_b_path, "frontal")
            db.add(StudentPhoto(
                id=uuid.uuid4(),
                student_id=student_b_id,
                photo_path=photo_b_path,
                view="front",
                file_size=os.path.getsize(photo_b_path),
                mime_type="image/jpeg",
                md5_hash="hash_b"
            ))

            await db.commit()

    asyncio.run(seed_students())

    # -------------------------------------------------------------
    # TEST 1: Known Registered Student in Violence Event
    # -------------------------------------------------------------
    print("\n[TEST 1] Testing identification of a known registered student...")
    v1_id = uuid.uuid4()
    inc1_id = uuid.uuid4()
    det1_id = uuid.uuid4()
    trk1_id = uuid.uuid4()

    crop_a_path = os.path.join(storage_dir, "crops", "crop_student_a.jpg")
    create_dummy_crop(crop_a_path, "frontal")

    async def setup_test_1():
        async with SessionLocal() as db:
            v1 = Video(
                id=v1_id,
                title="Cafeteria Incident",
                filename="test_student_id_source.mp4",
                original_filename="cafeteria_cctv.mp4",
                file_path=test_video_path,
                status="completed",
                duration=10.0,
                width=320,
                height=240,
                fps=10.0,
                camera_id=cam_id,
                uploaded_by=user_id,
                created_at=base_time
            )
            db.add(v1)

            inc1 = Incident(
                id=inc1_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=4.0),
                camera_id=cam_id,
                confidence=0.91,
                explanation="Detected physical fight at 4.0s."
            )
            db.add(inc1)

            det1 = DetectedEvent(
                id=det1_id,
                incident_id=inc1_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v1_id,
                timestamp=base_time + timedelta(seconds=4.0),
                track_id=trk1_id,
                confidence=0.91
            )
            db.add(det1)

            trk1 = Track(
                id=trk1_id,
                video_id=v1_id,
                object_class="person",
                tracker_id=1,
                start_time=2.0,
                end_time=6.0,
                key_frame_path=crop_a_path
            )
            db.add(trk1)

            db.add(Detection(
                id=uuid.uuid4(),
                track_id=trk1_id,
                frame_number=20,
                timestamp_seconds=4.0,
                bounding_box=[60.0, 40.0, 140.0, 200.0],
                confidence=0.92
            ))
            await db.commit()

    asyncio.run(setup_test_1())

    # Mock StudentIdentifier to return Student A match (0.87 similarity)
    with patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop") as mock_identify:
        mock_identify.return_value = {
            "success": True,
            "student_id": student_a_id,
            "similarity_score": 0.87,
            "confidence": "high"
        }

        async def run_compile_1():
            async with SessionLocal() as db:
                vid = await db.get(Video, v1_id)
                cam = await db.get(Camera, cam_id)
                return await _compile_violence_dossier(db, vid, cam)

        dossier1 = asyncio.run(run_compile_1())

    assert dossier1.status == "VIOLENCE_DETECTED"
    assert len(dossier1.segments) == 1
    seg1 = dossier1.segments[0]
    assert len(seg1.students) == 1, f"Expected 1 student, got {len(seg1.students)}"
    st1 = seg1.students[0]

    # Validate required fields
    assert st1.is_identified is True
    assert st1.student_id == student_a_id
    assert st1.name == "Aarav Sharma"
    assert st1.roll_number == "CS2024001"
    assert st1.class_name == "B.Tech CS Section A"
    assert st1.profile_photo_url is not None
    assert st1.similarity_score == 0.87
    assert st1.confidence == "high"
    assert st1.track_id == str(trk1_id)
    assert st1.event_id == str(det1_id)
    print(f"  --> Identified student: {st1.name} | Roll: {st1.roll_number} | Class: {st1.class_name}")
    print(f"  --> Similarity Score: {st1.similarity_score} | Track: {st1.track_id[:8]}... | Event: {st1.event_id[:8]}...")
    print("  --> PASSED: Known registered student successfully identified with full metadata.")

    # -------------------------------------------------------------
    # TEST 2: Multiple Registered Students in Violence Event
    # -------------------------------------------------------------
    print("\n[TEST 2] Testing multiple registered students in single violence event...")
    v2_id = uuid.uuid4()
    inc2_id = uuid.uuid4()
    det2_id = uuid.uuid4()
    trk2_a_id = uuid.uuid4()
    trk2_b_id = uuid.uuid4()

    crop_b_path = os.path.join(storage_dir, "crops", "crop_student_b.jpg")
    create_dummy_crop(crop_b_path, "frontal")

    async def setup_test_2():
        async with SessionLocal() as db:
            v2 = Video(
                id=v2_id,
                title="Quad Altercation",
                filename="test_student_id_source.mp4",
                original_filename="quad_cctv.mp4",
                file_path=test_video_path,
                status="completed",
                duration=10.0,
                width=320,
                height=240,
                fps=10.0,
                camera_id=cam_id,
                uploaded_by=user_id,
                created_at=base_time
            )
            db.add(v2)

            inc2 = Incident(
                id=inc2_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=5.0),
                camera_id=cam_id,
                confidence=0.94,
                explanation="Detected physical fight at 5.0s."
            )
            db.add(inc2)

            db.add(DetectedEvent(
                id=det2_id,
                incident_id=inc2_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v2_id,
                timestamp=base_time + timedelta(seconds=5.0),
                confidence=0.94
            ))

            # Track 1: Student A
            db.add(Track(
                id=trk2_a_id,
                video_id=v2_id,
                object_class="person",
                tracker_id=1,
                start_time=2.0,
                end_time=8.0,
                key_frame_path=crop_a_path
            ))
            db.add(Detection(
                id=uuid.uuid4(),
                track_id=trk2_a_id,
                frame_number=25,
                timestamp_seconds=5.0,
                bounding_box=[50.0, 40.0, 110.0, 190.0],
                confidence=0.91
            ))

            # Track 2: Student B
            db.add(Track(
                id=trk2_b_id,
                video_id=v2_id,
                object_class="person",
                tracker_id=2,
                start_time=2.0,
                end_time=8.0,
                key_frame_path=crop_b_path
            ))
            db.add(Detection(
                id=uuid.uuid4(),
                track_id=trk2_b_id,
                frame_number=25,
                timestamp_seconds=5.0,
                bounding_box=[150.0, 45.0, 210.0, 195.0],
                confidence=0.89
            ))
            await db.commit()

    asyncio.run(setup_test_2())

    # Mock StudentIdentifier to return Student A for crop_a and Student B for crop_b
    async def mock_multi_identify(crop_path):
        if "crop_student_a" in crop_path:
            return {"success": True, "student_id": student_a_id, "similarity_score": 0.88, "confidence": "high"}
        elif "crop_student_b" in crop_path:
            return {"success": True, "student_id": student_b_id, "similarity_score": 0.84, "confidence": "high"}
        return None

    with patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop", side_effect=mock_multi_identify):
        async def run_compile_2():
            async with SessionLocal() as db:
                vid = await db.get(Video, v2_id)
                cam = await db.get(Camera, cam_id)
                return await _compile_violence_dossier(db, vid, cam)

        dossier2 = asyncio.run(run_compile_2())

    seg2 = dossier2.segments[0]
    assert len(seg2.students) == 2, f"Expected 2 students, got {len(seg2.students)}"
    identified_ids = {s.student_id for s in seg2.students}
    assert identified_ids == {student_a_id, student_b_id}
    names = {s.name for s in seg2.students}
    assert names == {"Aarav Sharma", "Priya Patel"}
    print(f"  --> Identified multiple students in segment: {names}")
    print("  --> PASSED: Multiple registered students identified distinctly across tracks.")

    # -------------------------------------------------------------
    # TEST 3: Unknown Person (Below Threshold / No Match)
    # -------------------------------------------------------------
    print("\n[TEST 3] Testing unknown person (returns 'Unidentified Person', not forced)...")
    v3_id = uuid.uuid4()
    inc3_id = uuid.uuid4()
    trk3_id = uuid.uuid4()
    crop_unknown = os.path.join(storage_dir, "crops", "crop_unknown.jpg")
    create_dummy_crop(crop_unknown, "frontal")

    async def setup_test_3():
        async with SessionLocal() as db:
            v3 = Video(
                id=v3_id,
                title="Unknown Person Fight",
                filename="test_student_id_source.mp4",
                original_filename="unknown_fight.mp4",
                file_path=test_video_path,
                status="completed",
                duration=10.0,
                camera_id=cam_id,
                uploaded_by=user_id,
                created_at=base_time
            )
            db.add(v3)
            inc3 = Incident(
                id=inc3_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=3.0),
                camera_id=cam_id,
                confidence=0.85,
                explanation="Altercation at 3.0s."
            )
            db.add(inc3)
            db.add(DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc3_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v3_id,
                timestamp=base_time + timedelta(seconds=3.0),
                confidence=0.85
            ))
            db.add(Track(
                id=trk3_id,
                video_id=v3_id,
                object_class="person",
                tracker_id=5,
                start_time=1.0,
                end_time=5.0,
                key_frame_path=crop_unknown
            ))
            db.add(Detection(
                id=uuid.uuid4(),
                track_id=trk3_id,
                frame_number=15,
                timestamp_seconds=3.0,
                bounding_box=[70.0, 50.0, 130.0, 190.0],
                confidence=0.88
            ))
            await db.commit()

    asyncio.run(setup_test_3())

    # Mock StudentIdentifier to return None (similarity was below threshold e.g. 0.25 < 0.40)
    with patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop", return_value=None):
        async def run_compile_3():
            async with SessionLocal() as db:
                vid = await db.get(Video, v3_id)
                cam = await db.get(Camera, cam_id)
                return await _compile_violence_dossier(db, vid, cam)

        dossier3 = asyncio.run(run_compile_3())

    seg3 = dossier3.segments[0]
    assert len(seg3.students) >= 1
    st3 = seg3.students[0]
    assert st3.is_identified is False
    assert st3.name == "Unidentified Person"
    assert st3.student_id is None
    assert st3.roll_number == "N/A"
    assert st3.class_name == "Unknown Class"
    assert st3.confidence == "unidentified"
    assert st3.track_id == str(trk3_id)
    print(f"  --> Unknown person result: '{st3.name}', student_id={st3.student_id}, is_identified={st3.is_identified}")
    print("  --> PASSED: Unknown person cleanly classified as 'Unidentified Person' without forced match.")

    # -------------------------------------------------------------
    # TEST 4: Poor-Quality Face (Severe Blur / Fails Quality Gates)
    # -------------------------------------------------------------
    print("\n[TEST 4] Testing poor-quality blurry face (fails quality gates)...")
    v4_id = uuid.uuid4()
    inc4_id = uuid.uuid4()
    trk4_id = uuid.uuid4()
    crop_blurry = os.path.join(storage_dir, "crops", "crop_blurry.jpg")
    create_dummy_crop(crop_blurry, "blurry")

    async def setup_test_4():
        async with SessionLocal() as db:
            v4 = Video(
                id=v4_id,
                title="Blurry Face Fight",
                filename="test_student_id_source.mp4",
                original_filename="blur_fight.mp4",
                file_path=test_video_path,
                status="completed",
                duration=10.0,
                camera_id=cam_id,
                uploaded_by=user_id,
                created_at=base_time
            )
            db.add(v4)
            inc4 = Incident(
                id=inc4_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=2.0),
                camera_id=cam_id,
                confidence=0.82,
                explanation="Altercation at 2.0s."
            )
            db.add(inc4)
            db.add(DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc4_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v4_id,
                timestamp=base_time + timedelta(seconds=2.0),
                confidence=0.82
            ))
            db.add(Track(
                id=trk4_id,
                video_id=v4_id,
                object_class="person",
                tracker_id=8,
                start_time=0.0,
                end_time=4.0,
                key_frame_path=crop_blurry
            ))
            db.add(Detection(
                id=uuid.uuid4(),
                track_id=trk4_id,
                frame_number=10,
                timestamp_seconds=2.0,
                bounding_box=[50.0, 50.0, 110.0, 180.0],
                confidence=0.80
            ))
            await db.commit()

    asyncio.run(setup_test_4())

    with patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop", return_value=None):
        async def run_compile_4():
            async with SessionLocal() as db:
                vid = await db.get(Video, v4_id)
                cam = await db.get(Camera, cam_id)
                return await _compile_violence_dossier(db, vid, cam)

        dossier4 = asyncio.run(run_compile_4())

    st4 = dossier4.segments[0].students[0]
    assert st4.is_identified is False
    assert st4.name == "Unidentified Person"
    print(f"  --> Blurry crop handled gracefully: '{st4.name}', confidence={st4.confidence}")
    print("  --> PASSED: Poor quality blurry face handled without exceptions.")

    # -------------------------------------------------------------
    # TEST 5: Side Profile Face
    # -------------------------------------------------------------
    print("\n[TEST 5] Testing side profile face (non-frontal angle)...")
    v5_id = uuid.uuid4()
    inc5_id = uuid.uuid4()
    trk5_id = uuid.uuid4()
    crop_side = os.path.join(storage_dir, "crops", "crop_side.jpg")
    create_dummy_crop(crop_side, "side_profile")

    async def setup_test_5():
        async with SessionLocal() as db:
            v5 = Video(
                id=v5_id,
                title="Side Profile Fight",
                filename="test_student_id_source.mp4",
                original_filename="side_fight.mp4",
                file_path=test_video_path,
                status="completed",
                duration=10.0,
                camera_id=cam_id,
                uploaded_by=user_id,
                created_at=base_time
            )
            db.add(v5)
            inc5 = Incident(
                id=inc5_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=6.0),
                camera_id=cam_id,
                confidence=0.88,
                explanation="Altercation at 6.0s."
            )
            db.add(inc5)
            db.add(DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc5_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v5_id,
                timestamp=base_time + timedelta(seconds=6.0),
                confidence=0.88
            ))
            db.add(Track(
                id=trk5_id,
                video_id=v5_id,
                object_class="person",
                tracker_id=12,
                start_time=4.0,
                end_time=8.0,
                key_frame_path=crop_side
            ))
            db.add(Detection(
                id=uuid.uuid4(),
                track_id=trk5_id,
                frame_number=30,
                timestamp_seconds=6.0,
                bounding_box=[80.0, 60.0, 140.0, 190.0],
                confidence=0.84
            ))
            await db.commit()

    asyncio.run(setup_test_5())

    with patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop", return_value=None):
        async def run_compile_5():
            async with SessionLocal() as db:
                vid = await db.get(Video, v5_id)
                cam = await db.get(Camera, cam_id)
                return await _compile_violence_dossier(db, vid, cam)

        dossier5 = asyncio.run(run_compile_5())

    st5 = dossier5.segments[0].students[0]
    assert st5.name == "Unidentified Person"
    assert st5.is_identified is False
    print(f"  --> Side profile handled: '{st5.name}' (unforced match)")
    print("  --> PASSED: Side profile gracefully handled.")

    # -------------------------------------------------------------
    # TEST 6: No Face Visible (Back Turned / Occluded)
    # -------------------------------------------------------------
    print("\n[TEST 6] Testing person with no face visible (back turned)...")
    v6_id = uuid.uuid4()
    inc6_id = uuid.uuid4()
    trk6_id = uuid.uuid4()
    crop_noface = os.path.join(storage_dir, "crops", "crop_noface.jpg")
    create_dummy_crop(crop_noface, "no_face")

    async def setup_test_6():
        async with SessionLocal() as db:
            v6 = Video(
                id=v6_id,
                title="No Face Fight",
                filename="test_student_id_source.mp4",
                original_filename="noface_fight.mp4",
                file_path=test_video_path,
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
                timestamp=base_time + timedelta(seconds=7.0),
                camera_id=cam_id,
                confidence=0.90,
                explanation="Altercation at 7.0s."
            )
            db.add(inc6)
            db.add(DetectedEvent(
                id=uuid.uuid4(),
                incident_id=inc6_id,
                event_type="FIGHT",
                camera_id=cam_id,
                video_id=v6_id,
                timestamp=base_time + timedelta(seconds=7.0),
                confidence=0.90
            ))
            db.add(Track(
                id=trk6_id,
                video_id=v6_id,
                object_class="person",
                tracker_id=15,
                start_time=5.0,
                end_time=9.0,
                key_frame_path=crop_noface
            ))
            db.add(Detection(
                id=uuid.uuid4(),
                track_id=trk6_id,
                frame_number=35,
                timestamp_seconds=7.0,
                bounding_box=[100.0, 70.0, 160.0, 200.0],
                confidence=0.86
            ))
            await db.commit()

    asyncio.run(setup_test_6())

    with patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop", return_value=None):
        async def run_compile_6():
            async with SessionLocal() as db:
                vid = await db.get(Video, v6_id)
                cam = await db.get(Camera, cam_id)
                return await _compile_violence_dossier(db, vid, cam)

        dossier6 = asyncio.run(run_compile_6())

    st6 = dossier6.segments[0].students[0]
    assert st6.name == "Unidentified Person"
    assert st6.is_identified is False
    print(f"  --> No-face person handled: '{st6.name}'")
    print("  --> PASSED: Person without visible face cleanly preserved as Unidentified Person.")

    # -------------------------------------------------------------
    # TEST 7: Confidence Differentiation & UI Wording Integrity
    # -------------------------------------------------------------
    print("\n[TEST 7] Verifying distinct Violence vs Identity confidence & non-accusatory UI wording...")
    seg = dossier1.segments[0]
    violence_conf = seg.confidence
    student = seg.students[0]
    identity_conf = student.similarity_score

    assert violence_conf == 0.91, f"Expected 0.91 violence confidence, got {violence_conf}"
    assert identity_conf == 0.87, f"Expected 0.87 identity confidence, got {identity_conf}"
    assert violence_conf != identity_conf, "Violence confidence and Identity confidence must be distinctly tracked"
    print(f"  --> Violence Confidence: {violence_conf * 100:.0f}% (Incident Severity)")
    print(f"  --> Identity Match Confidence: {identity_conf * 100:.0f}% (Biometric ArcFace)")

    # Verify frontend file contains the required non-accusatory wording
    frontend_file = os.path.join(backend_path, "..", "frontend", "src", "pages", "ViolenceDetection.tsx")
    with open(frontend_file, "r", encoding="utf-8") as f:
        frontend_code = f.read()

    assert "Person identified in detected violence event" in frontend_code, \
        "Frontend MUST display 'Person identified in detected violence event'"
    assert "is definitely fighting" not in frontend_code, \
        "Frontend MUST NOT say 'is definitely fighting'"
    print("  --> PASSED: Confidences clearly differentiated; non-accusatory wording verified.")

    print("\n=======================================================")
    print("  ALL 7 STUDENT IDENTIFICATION TESTS PASSED (7/7)!")
    print("=======================================================\n")

if __name__ == "__main__":
    run_student_identification_tests()
