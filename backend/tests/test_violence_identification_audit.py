"""
Targeted Regression Test Suite for Violence Person Identification Audit
Validates:
1. Correctly associating a person crop with its track.
2. Preventing one person's face from being assigned to another person's track.
3. Rejecting low-quality or ambiguous identity matches.
4. Preserving an unidentified result when confidence is insufficient.
5. Aggregating valid observations without duplicating identities across concurrent tracks.
6. Keeping existing violence detection behavior and parameters unchanged.
"""

import os
import sys
import uuid
import hashlib
import unittest
import numpy as np
import cv2
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

# Environment setup
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_audit_regression.db"

sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import asyncio
from app.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.db.base_class import Base
from app.models.user import User
from app.models.camera import Camera
from app.models.video import Video
from app.models.student import Student, StudentPhoto
from app.models.track import Track, Detection
from app.models.incident import Incident, DetectedEvent, IncidentPerson
from app.models.recognition import StudentRecognitionEvent
from app.schemas.violence import InvolvedStudentCard
from app.api.v1.violence import _compile_violence_dossier
from app.services.student_identifier import StudentIdentifier

test_db_file = os.path.join(backend_dir, "storage", "test_audit_regression.db")
test_db_url = f"sqlite+aiosqlite:///{test_db_file.replace(os.sep, '/')}"
test_engine = create_async_engine(test_db_url, echo=False)
TestSessionLocal = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)


def create_dummy_crop_image(filepath: str, is_blurry: bool = False):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    img = np.zeros((160, 100, 3), dtype=np.uint8)
    cv2.circle(img, (50, 45), 25, (220, 220, 220), -1)
    cv2.circle(img, (40, 40), 4, (40, 40, 40), -1)
    cv2.circle(img, (60, 40), 4, (40, 40, 40), -1)
    if is_blurry:
        img = cv2.GaussianBlur(img, (25, 25), 10.0)
    cv2.imwrite(filepath, img)


def make_user(u_id: uuid.UUID) -> User:
    return User(
        id=u_id,
        email=f"admin_{uuid.uuid4().hex[:6]}@smartcampus.edu",
        hashed_password="fakepassword",
        role="admin"
    )


def make_cam(cam_id: uuid.UUID, name: str = "Test Cam") -> Camera:
    return Camera(
        id=cam_id,
        name=name,
        building="Administrative Block",
        floor=1,
        location="Courtyard",
        direction="North",
        resolution="1920x1080",
        status="active"
    )


def make_student(student_id: uuid.UUID, name: str = "Test Student", roll: str = "CS101") -> Student:
    return Student(
        id=student_id,
        university_roll_number=roll,
        name=name,
        department="Computer Science & Engineering",
        programme="B.Tech CS",
        year=3,
        semester=5,
        section="Section A",
        email=f"{uuid.uuid4().hex[:8]}@smartcampus.edu",
        status="active"
    )


def make_video(v_id: uuid.UUID, cam_id: uuid.UUID, user_id: uuid.UUID, filename: str = "v.mp4") -> Video:
    return Video(
        id=v_id,
        title="Test Video",
        filename=filename,
        original_filename=filename,
        file_path=filename,
        duration=10.0,
        camera_id=cam_id,
        uploaded_by=user_id,
        status="completed"
    )


class TestViolenceIdentificationRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(cls.loop)
        cls.loop.run_until_complete(cls._init_db())

    @classmethod
    def tearDownClass(cls):
        cls.loop.run_until_complete(test_engine.dispose())
        cls.loop.close()

    @classmethod
    async def _init_db(cls):
        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    def test_1_crop_associated_with_correct_track(self):
        """1. Verify that each person crop is strictly associated with its own track."""
        u_id = uuid.uuid4()
        v_id = uuid.uuid4()
        c_id = uuid.uuid4()
        t1_id = uuid.uuid4()
        t2_id = uuid.uuid4()
        inc_id = uuid.uuid4()
        crop1 = os.path.join(settings.STORAGE_DIR, "crops", f"t1_{uuid.uuid4().hex[:6]}.jpg")
        crop2 = os.path.join(settings.STORAGE_DIR, "crops", f"t2_{uuid.uuid4().hex[:6]}.jpg")
        create_dummy_crop_image(crop1)
        create_dummy_crop_image(crop2)

        async def setup():
            async with TestSessionLocal() as db:
                user = make_user(u_id)
                db.add(user)
                cam = make_cam(c_id, f"Cam 1 {uuid.uuid4().hex[:4]}")
                db.add(cam)
                vid = make_video(v_id, c_id, u_id, "v1.mp4")
                db.add(vid)
                inc = Incident(id=inc_id, incident_type="Violence", camera_id=c_id, confidence=0.88, explanation="altercation from 1.0s to 4.0s")
                db.add(inc)
                db.add(DetectedEvent(id=uuid.uuid4(), incident_id=inc_id, video_id=v_id, camera_id=c_id, event_type="VIOLENCE", confidence=0.88))
                trk1 = Track(id=t1_id, video_id=v_id, object_class="person", tracker_id=1, start_time=1.0, end_time=4.0, key_frame_path=crop1)
                trk2 = Track(id=t2_id, video_id=v_id, object_class="person", tracker_id=2, start_time=1.0, end_time=4.0, key_frame_path=crop2)
                db.add(trk1)
                db.add(trk2)
                db.add(Detection(id=uuid.uuid4(), track_id=t1_id, frame_number=10, timestamp_seconds=2.0, bounding_box=[10, 10, 50, 100], confidence=0.9))
                db.add(Detection(id=uuid.uuid4(), track_id=t2_id, frame_number=10, timestamp_seconds=2.0, bounding_box=[60, 10, 110, 100], confidence=0.9))
                await db.commit()

        self.loop.run_until_complete(setup())

        async def run_dossier():
            async with TestSessionLocal() as db:
                v = await db.get(Video, v_id)
                c = await db.get(Camera, c_id)
                return await _compile_violence_dossier(db, v, c)

        dossier = self.loop.run_until_complete(run_dossier())
        seg = dossier.segments[0]
        self.assertEqual(len(seg.tracks), 2)
        track_map = {t.track_id: t for t in seg.tracks}
        self.assertIn(str(t1_id), track_map)
        self.assertIn(str(t2_id), track_map)
        self.assertIn(os.path.basename(crop1), track_map[str(t1_id)].person_crop)
        self.assertIn(os.path.basename(crop2), track_map[str(t2_id)].person_crop)

    def test_2_preventing_cross_track_face_assignment(self):
        """2. Verify that one person's face/identity is NOT assigned to another person's track."""
        u_id = uuid.uuid4()
        v_id = uuid.uuid4()
        c_id = uuid.uuid4()
        t1_id = uuid.uuid4()
        t2_id = uuid.uuid4()
        s_id = uuid.uuid4()
        inc_id = uuid.uuid4()

        async def setup():
            async with TestSessionLocal() as db:
                db.add(make_user(u_id))
                db.add(make_cam(c_id, f"Cam 2 {uuid.uuid4().hex[:4]}"))
                db.add(make_video(v_id, c_id, u_id, "v2.mp4"))
                std = make_student(s_id, name="Target Student", roll=f"R_{uuid.uuid4().hex[:4]}")
                db.add(std)
                inc = Incident(id=inc_id, incident_type="Violence", camera_id=c_id, confidence=0.90, explanation="altercation from 2.0s to 5.0s")
                db.add(inc)
                db.add(DetectedEvent(id=uuid.uuid4(), incident_id=inc_id, video_id=v_id, camera_id=c_id, event_type="VIOLENCE", confidence=0.90))
                trk1 = Track(id=t1_id, video_id=v_id, object_class="person", tracker_id=1, start_time=2.0, end_time=5.0, identified_student_id=s_id)
                trk2 = Track(id=t2_id, video_id=v_id, object_class="person", tracker_id=2, start_time=2.0, end_time=5.0, identified_student_id=None)
                db.add(trk1)
                db.add(trk2)
                db.add(Detection(id=uuid.uuid4(), track_id=t1_id, frame_number=20, timestamp_seconds=3.0, bounding_box=[10, 10, 50, 100], confidence=0.9))
                db.add(Detection(id=uuid.uuid4(), track_id=t2_id, frame_number=20, timestamp_seconds=3.0, bounding_box=[60, 10, 110, 100], confidence=0.9))
                db.add(StudentRecognitionEvent(
                    id=uuid.uuid4(),
                    track_id=t1_id,
                    student_id=s_id,
                    video_id=v_id,
                    timestamp=datetime.now(timezone.utc),
                    similarity_score=0.85,
                    confidence="high"
                ))
                await db.commit()

        self.loop.run_until_complete(setup())

        async def run_dossier():
            async with TestSessionLocal() as db:
                v = await db.get(Video, v_id)
                c = await db.get(Camera, c_id)
                return await _compile_violence_dossier(db, v, c)

        dossier = self.loop.run_until_complete(run_dossier())
        seg = dossier.segments[0]
        track_cards = {t.track_id: t.identified_student for t in seg.tracks}

        self.assertEqual(track_cards[str(t1_id)].name, "Target Student")
        self.assertTrue(track_cards[str(t1_id)].is_identified)

        self.assertNotEqual(track_cards[str(t2_id)].name, "Target Student")
        self.assertEqual(track_cards[str(t2_id)].name, "Unidentified Person")
        self.assertFalse(track_cards[str(t2_id)].is_identified)

    def test_3_rejecting_ambiguous_identity_matches(self):
        """3. Verify rejection when top similarity is ambiguous with a second enrolled candidate (< 0.05 margin)."""
        identifier = StudentIdentifier()
        emb_query = [0.1] * 512

        sid_1 = uuid.uuid4()
        sid_2 = uuid.uuid4()

        mock_point_1 = MagicMock(id="p1", score=0.68, payload={"student_id": str(sid_1)})
        mock_point_2 = MagicMock(id="p2", score=0.66, payload={"student_id": str(sid_2)})
        mock_resp = MagicMock(points=[mock_point_1, mock_point_2])

        with patch.object(identifier.face_engine, "process_photo", return_value={
            "success": True, "embedding": emb_query, "quality_score": 0.9, "bbox": [10, 10, 50, 50]
        }):
            with patch.object(identifier.vector_store.client, "query_points", return_value=mock_resp):
                res = self.loop.run_until_complete(identifier.identify_face_in_crop("dummy_path.jpg"))
                self.assertIsNone(res, "Ambiguous match between two enrolled students must be rejected")

    def test_4_preserving_unidentified_when_confidence_insufficient(self):
        """4. Verify that unknown or sub-threshold matches cleanly preserve Unidentified Person."""
        u_id = uuid.uuid4()
        v_id = uuid.uuid4()
        c_id = uuid.uuid4()
        t_id = uuid.uuid4()
        inc_id = uuid.uuid4()

        async def setup():
            async with TestSessionLocal() as db:
                db.add(make_user(u_id))
                db.add(make_cam(c_id, f"Cam 4 {uuid.uuid4().hex[:4]}"))
                db.add(make_video(v_id, c_id, u_id, "v4.mp4"))
                inc = Incident(id=inc_id, incident_type="Violence", camera_id=c_id, confidence=0.85, explanation="altercation from 3.0s to 6.0s")
                db.add(inc)
                db.add(DetectedEvent(id=uuid.uuid4(), incident_id=inc_id, video_id=v_id, camera_id=c_id, event_type="VIOLENCE", confidence=0.85))
                trk = Track(id=t_id, video_id=v_id, object_class="person", tracker_id=99, start_time=3.0, end_time=6.0, identified_student_id=None)
                db.add(trk)
                db.add(Detection(id=uuid.uuid4(), track_id=t_id, frame_number=30, timestamp_seconds=4.0, bounding_box=[20, 20, 80, 120], confidence=0.85))
                await db.commit()

        self.loop.run_until_complete(setup())

        with patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop", return_value=None):
            async def run_dossier():
                async with TestSessionLocal() as db:
                    v = await db.get(Video, v_id)
                    c = await db.get(Camera, c_id)
                    return await _compile_violence_dossier(db, v, c)

            dossier = self.loop.run_until_complete(run_dossier())

        seg = dossier.segments[0]
        self.assertGreaterEqual(len(seg.students), 1)
        st = seg.students[0]
        self.assertEqual(st.name, "Unidentified Person")
        self.assertIsNone(st.student_id)
        self.assertFalse(st.is_identified)
        self.assertEqual(st.confidence, "unidentified")

    def test_5_aggregating_observations_without_duplicating_identities(self):
        """5. Verify that multiple concurrent tracks in the same altercation do not duplicate the same student."""
        from app.api.v1.violence import _compile_violence_dossier
        u_id = uuid.uuid4()
        v_id = uuid.uuid4()
        c_id = uuid.uuid4()
        t1_id = uuid.uuid4()
        t2_id = uuid.uuid4()
        s_id = uuid.uuid4()
        inc_id = uuid.uuid4()

        async def setup():
            async with TestSessionLocal() as db:
                db.add(make_user(u_id))
                db.add(make_cam(c_id, f"Cam 5 {uuid.uuid4().hex[:4]}"))
                db.add(make_video(v_id, c_id, u_id, "v5.mp4"))
                std = make_student(s_id, name="Meera Nair", roll=f"R_{uuid.uuid4().hex[:4]}")
                db.add(std)
                inc = Incident(id=inc_id, incident_type="Violence", camera_id=c_id, confidence=0.92, explanation="altercation from 1.0s to 5.0s")
                db.add(inc)
                db.add(DetectedEvent(id=uuid.uuid4(), incident_id=inc_id, video_id=v_id, camera_id=c_id, event_type="VIOLENCE", confidence=0.92))
                trk1 = Track(id=t1_id, video_id=v_id, object_class="person", tracker_id=1, start_time=1.0, end_time=5.0, identified_student_id=s_id)
                trk2 = Track(id=t2_id, video_id=v_id, object_class="person", tracker_id=2, start_time=1.0, end_time=5.0, identified_student_id=None)
                db.add(trk1)
                db.add(trk2)
                db.add(Detection(id=uuid.uuid4(), track_id=t1_id, frame_number=15, timestamp_seconds=2.0, bounding_box=[10, 10, 50, 100], confidence=0.9))
                db.add(Detection(id=uuid.uuid4(), track_id=t2_id, frame_number=15, timestamp_seconds=2.0, bounding_box=[60, 10, 110, 100], confidence=0.9))
                db.add(StudentRecognitionEvent(
                    id=uuid.uuid4(), track_id=t1_id, student_id=s_id, video_id=v_id,
                    timestamp=datetime.now(timezone.utc), similarity_score=0.88, confidence="high"
                ))
                await db.commit()

        self.loop.run_until_complete(setup())

        async def mock_crop_identify(crop_path):
            return {"success": True, "student_id": s_id, "similarity_score": 0.65, "confidence": "medium"}

        with patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop", side_effect=mock_crop_identify):
            async def run_dossier():
                async with TestSessionLocal() as db:
                    v = await db.get(Video, v_id)
                    c = await db.get(Camera, c_id)
                    return await _compile_violence_dossier(db, v, c)

            dossier = self.loop.run_until_complete(run_dossier())

        seg = dossier.segments[0]
        meera_count = sum(1 for st in seg.students if st.student_id == s_id)
        self.assertEqual(meera_count, 1, "An enrolled student must not be duplicated across multiple tracks in the same segment")

    def test_6_preserved_x3d_checkpoint_and_parameters(self):
        """6. Verify X3D checkpoint SHA-256 and locked parameters remain strictly preserved."""
        expected_hash = "e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349"
        ckpt_path = os.path.join(settings.STORAGE_DIR, "models", "x3d", "final_x3d_realtime.pt")
        self.assertTrue(os.path.exists(ckpt_path), f"Checkpoint missing: {ckpt_path}")

        hasher = hashlib.sha256()
        with open(ckpt_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        actual_hash = hasher.hexdigest()
        self.assertEqual(actual_hash, expected_hash, "X3D checkpoint SHA-256 hash mismatch!")

        from app.pipeline.x3d_violence_detector import X3DViolenceDetector
        detector = X3DViolenceDetector()
        self.assertEqual(detector.threshold, 0.40, "X3D violence threshold must remain 0.40")
        self.assertEqual(detector.num_frames, 16, "X3D window frame count must remain 16")
        self.assertEqual(detector.mean, (0.45, 0.45, 0.45))
        self.assertEqual(detector.std, (0.225, 0.225, 0.225))
        self.assertEqual(settings.RECOGNITION_MEDIUM_THRESHOLD, 0.60)
        self.assertEqual(settings.RECOGNITION_HIGH_THRESHOLD, 0.75)


if __name__ == "__main__":
    unittest.main()
