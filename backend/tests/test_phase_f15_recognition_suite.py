import os
import sys
import unittest
import hashlib
import json
import uuid

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi.testclient import TestClient
from app.main import app
from app.core.config import settings
from app.core.security import create_access_token
import sqlite3

class TestPhaseF15RecognitionSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.token = create_access_token("23087cde-f8ca-4815-9769-0516754d6921")
        cls.headers = {"Authorization": f"Bearer {cls.token}"}
        cls.test_video_id = "58a574f8-0491-4206-9243-b9761f80898d"

    def test_1_x3d_checkpoint_and_parameters_preservation(self):
        """Verify X3D-M checkpoint hash and locked detection parameters remain untouched."""
        expected_hash = "e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349"
        ckpt_path = os.path.join(settings.STORAGE_DIR, "models", "x3d", "final_x3d_realtime.pt")
        self.assertTrue(os.path.exists(ckpt_path), f"Checkpoint missing: {ckpt_path}")
        
        hasher = hashlib.sha256()
        with open(ckpt_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        actual_hash = hasher.hexdigest()
        self.assertEqual(actual_hash, expected_hash, "X3D checkpoint SHA-256 hash mismatch!")

        # Recognition thresholds
        self.assertEqual(settings.RECOGNITION_MEDIUM_THRESHOLD, 0.60)
        self.assertEqual(settings.RECOGNITION_HIGH_THRESHOLD, 0.75)

    def test_2_enrolled_student_biometrics_intact(self):
        """Verify enrolled students and biometric embeddings remain intact in database."""
        db_path = os.path.join(settings.STORAGE_DIR, "cctv.db")
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        c.execute("PRAGMA foreign_key_check")
        fk_errors = c.fetchall()
        self.assertEqual(fk_errors, [], f"Foreign key errors detected: {fk_errors}")

        c.execute("SELECT s.name, COUNT(fe.id) FROM students s JOIN student_face_embeddings fe ON s.id = fe.student_id GROUP BY s.id")
        enrolled = dict(c.fetchall())
        conn.close()

        self.assertIn("Anukutty", enrolled)
        self.assertIn("Ashish P", enrolled)
        self.assertGreater(enrolled["Anukutty"], 0)
        self.assertGreater(enrolled["Ashish P"], 0)

    def test_3_violence_result_api_multi_student_identification(self):
        """Verify GET /violence/result/{vid} returns identified students in both root and segments."""
        resp = self.client.get(f"/api/v1/violence/result/{self.test_video_id}", headers=self.headers)
        self.assertEqual(resp.status_code, 200, f"Error: {resp.text}")
        data = resp.json()

        self.assertEqual(data.get("status"), "VIOLENCE_DETECTED")
        root_students = data.get("identified_students", [])
        self.assertGreaterEqual(len(root_students), 2, "Expected at least 2 identified students in root payload")

        student_names = [s.get("name") for s in root_students]
        self.assertIn("Anukutty", student_names)
        self.assertIn("Ashish P", student_names)

        for s in root_students:
            self.assertTrue(s.get("is_identified"), f"Student {s.get('name')} must have is_identified=True")
            self.assertGreaterEqual(s.get("similarity_score", 0), 0.60, f"Similarity below 0.60 threshold")

        segments = data.get("segments", [])
        self.assertGreaterEqual(len(segments), 1)
        for seg in segments:
            seg_students = seg.get("students", [])
            self.assertGreaterEqual(len(seg_students), 2, f"Segment {seg.get('segment_id')} missing identified students")
            seg_names = [st.get("name") for st in seg_students]
            self.assertIn("Anukutty", seg_names)
            self.assertIn("Ashish P", seg_names)

    def test_4_frontend_unidentified_safety(self):
        """Verify unidentified person cards cleanly preserve is_identified=False."""
        from app.schemas.violence import InvolvedStudentCard
        unidentified_card = InvolvedStudentCard(
            student_id=None,
            name="Unidentified Person",
            roll_number="N/A",
            similarity_score=0.0,
            confidence="unidentified",
            is_identified=False
        )
        self.assertFalse(unidentified_card.is_identified)
        self.assertIsNone(unidentified_card.student_id)
        self.assertEqual(unidentified_card.name, "Unidentified Person")

if __name__ == "__main__":
    unittest.main()
