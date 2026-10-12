import os
import sys
import uuid
import hashlib
import sqlite3
import unittest
import cv2
import numpy as np
from fastapi.testclient import TestClient

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.core.security import create_access_token
from app.main import app
from app.pipeline.x3d_violence_detector import X3DViolenceDetector
from app.tasks.video_tasks import cancel_video_processing, is_video_cancelled, _cancelled_video_ids

CHECKPOINT_PATH = os.path.join(settings.STORAGE_DIR, "models", "x3d", "final_x3d_realtime.pt")
EXPECTED_HASH = "e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349"

client = TestClient(app)

class TestPhaseF14Suite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        token = create_access_token("admin@smartcampus.com")
        cls.auth_headers = {"Authorization": f"Bearer {token}"}

    def test_1_x3d_checkpoint_and_parameters(self):
        """Verify X3D-M checkpoint hash and locked detection parameters."""
        self.assertTrue(os.path.exists(CHECKPOINT_PATH), f"Checkpoint missing at {CHECKPOINT_PATH}")
        with open(CHECKPOINT_PATH, "rb") as f:
            actual_hash = hashlib.sha256(f.read()).hexdigest()
        self.assertEqual(actual_hash, EXPECTED_HASH, f"Hash mismatch: expected {EXPECTED_HASH}, got {actual_hash}")

        # Parameters lock verification
        detector = X3DViolenceDetector()
        self.assertEqual(detector.num_frames, 16, "Window size must be 16 frames")
        self.assertEqual(settings.RECOGNITION_MEDIUM_THRESHOLD, 0.60, "Medium threshold must remain 0.60")
        self.assertEqual(settings.RECOGNITION_HIGH_THRESHOLD, 0.75, "High threshold must remain 0.75")

    def test_2_existing_crop_loads_correctly(self):
        """Test that an existing crop file in storage loads with 200 OK and valid image bytes."""
        test_crop_dir = os.path.join(settings.STORAGE_DIR, "crops", "test_f14_crop_unit")
        os.makedirs(test_crop_dir, exist_ok=True)
        test_crop_path = os.path.join(test_crop_dir, "crop_sample.jpg")
        
        # Create sample 100x100 dummy JPEG
        dummy_img = np.zeros((100, 100, 3), dtype=np.uint8)
        cv2.imwrite(test_crop_path, dummy_img)

        try:
            resp = client.get("/storage/crops/test_f14_crop_unit/crop_sample.jpg", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 200, f"Expected 200, got {resp.status_code}: {resp.text}")
            self.assertGreater(len(resp.content), 0)
        finally:
            if os.path.exists(test_crop_path):
                os.remove(test_crop_path)
            if os.path.exists(test_crop_dir):
                os.rmdir(test_crop_dir)

    def test_3_missing_crop_returns_404_cleanly(self):
        """Test that requesting non-existent crop returns 404 without crashing."""
        resp = client.get("/storage/crops/05dd6066-ad81-4a48-8611-d57bdf3e6f7c/1_12_d6a998.jpg", headers=self.auth_headers)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["detail"], "Requested file not found")

    def test_4_storage_path_normalization(self):
        """Test that redundant leading /storage/ or storage/ in path resolves to the same asset."""
        test_crop_dir = os.path.join(settings.STORAGE_DIR, "crops", "test_norm_unit")
        os.makedirs(test_crop_dir, exist_ok=True)
        test_crop_path = os.path.join(test_crop_dir, "norm_sample.jpg")
        cv2.imwrite(test_crop_path, np.zeros((50, 50, 3), dtype=np.uint8))

        try:
            # Normal path
            r1 = client.get("/storage/crops/test_norm_unit/norm_sample.jpg", headers=self.auth_headers)
            self.assertEqual(r1.status_code, 200)
            # Redundant storage prefix
            r2 = client.get("/storage/storage/crops/test_norm_unit/norm_sample.jpg", headers=self.auth_headers)
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(r1.content, r2.content)
        finally:
            if os.path.exists(test_crop_path):
                os.remove(test_crop_path)
            if os.path.exists(test_crop_dir):
                os.rmdir(test_crop_dir)

    def test_5_blocked_sensitive_files(self):
        """Ensure database and model checkpoint files cannot be downloaded via /storage/."""
        for sensitive in ["cctv.db", "sqlite_fallback.db", "models/x3d/final_x3d_realtime.pt"]:
            resp = client.get(f"/storage/{sensitive}", headers=self.auth_headers)
            self.assertEqual(resp.status_code, 403, f"Expected 403 for {sensitive}, got {resp.status_code}")

    def test_6_unauthenticated_storage_access_denied(self):
        """Ensure requests without authorization token return 401."""
        resp = client.get("/storage/crops/any/crop.jpg")
        self.assertEqual(resp.status_code, 401)

    def test_7_cancellation_still_works(self):
        """Verify cancellation flag mechanisms for pipeline workers."""
        vid = uuid.uuid4()
        self.assertFalse(is_video_cancelled(vid))
        cancel_video_processing(vid)
        self.assertTrue(is_video_cancelled(vid))
        _cancelled_video_ids.discard(str(vid))
        self.assertFalse(is_video_cancelled(vid))

    def test_8_database_foreign_key_integrity(self):
        """Verify SQLite database passes PRAGMA foreign_key_check and quick_check."""
        db_path = os.path.join(settings.STORAGE_DIR, "cctv.db")
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            c.execute("PRAGMA quick_check")
            quick_check = c.fetchall()
            self.assertEqual(quick_check, [("ok",)], f"Database corruption detected: {quick_check}")
            
            c.execute("PRAGMA foreign_key_check")
            fk_violations = c.fetchall()
            self.assertEqual(len(fk_violations), 0, f"Foreign key violations found: {fk_violations}")
            conn.close()

    def test_9_x3d_violence_detection_output(self):
        """Verify X3D detector produces valid windows and probabilities on test media."""
        p = os.path.join(settings.STORAGE_DIR, "test_debug_media", "x3d_fight_event.mp4")
        if os.path.exists(p):
            d = X3DViolenceDetector()
            res = d.detect_violence(p, threshold=0.4, window_duration_sec=2.0, stride_sec=1.0)
            self.assertGreater(res.total_frames, 0)
            self.assertGreaterEqual(len(res.windows), 1)
            self.assertGreaterEqual(res.overall_confidence, 0.0)
            self.assertLessEqual(res.overall_confidence, 1.0)

if __name__ == "__main__":
    unittest.main(verbosity=2)
