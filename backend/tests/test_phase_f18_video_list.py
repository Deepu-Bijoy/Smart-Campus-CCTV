import os
import sys
import uuid
from datetime import datetime, timezone
import unittest
from fastapi.testclient import TestClient

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.main import app
from app.core.security import create_access_token
from app.schemas.video import VideoResponse

class TestPhaseF18VideoList(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.token = create_access_token("23087cde-f8ca-4815-9769-0516754d6921")
        cls.headers = {"Authorization": f"Bearer {cls.token}"}
        cls.video_with_cam = None
        cls.test_cam_id = None
        cls.video_without_cam = None

        resp = cls.client.get("/api/v1/videos", headers=cls.headers)
        if resp.status_code == 200:
            for v in resp.json():
                if v.get("camera_id") and not cls.video_with_cam:
                    cls.video_with_cam = v["id"]
                    cls.test_cam_id = v["camera_id"]
                elif not v.get("camera_id") and not cls.video_without_cam:
                    cls.video_without_cam = v["id"]

    def test_1_video_associated_with_valid_camera_uuid(self):
        """Test that a video associated with a valid camera returns the camera UUID."""
        if not self.video_with_cam:
            self.skipTest("No video with associated camera found in database")
        resp = self.client.get(f"/api/v1/videos/{self.video_with_cam}", headers=self.headers)
        self.assertEqual(resp.status_code, 200, f"Expected 200, got {resp.status_code}: {resp.text}")
        data = resp.json()
        self.assertEqual(data.get("camera_id"), self.test_cam_id)
        # Verify it parses as a genuine UUID
        parsed_uuid = uuid.UUID(data["camera_id"])
        self.assertEqual(str(parsed_uuid), self.test_cam_id)

    def test_2_video_with_no_camera_or_invalid_metadata_handled_explicitly(self):
        """Test that invalid internal metadata descriptor is handled explicitly, returning None."""
        if self.video_without_cam:
            resp = self.client.get(f"/api/v1/videos/{self.video_without_cam}", headers=self.headers)
            self.assertEqual(resp.status_code, 200, f"Expected 200, got {resp.status_code}: {resp.text}")
            data = resp.json()
            self.assertIsNone(data.get("camera_id"), "Invalid metadata must be cleanly mapped to None")
        # Direct schema test with descriptor string
        sample_video_dict = {
            "id": uuid.uuid4(),
            "filename": "desc_test.mp4",
            "original_filename": "desc_test.mp4",
            "file_path": "/storage/desc_test.mp4",
            "status": "completed",
            "progress_percentage": 100,
            "camera_id": "annotation=Union[UUID, NoneType] required=False default=None alias='camera_id' json_schema_extra={}",
            "uploaded_by": uuid.uuid4(),
            "created_at": datetime.now(timezone.utc)
        }
        res = VideoResponse.model_validate(sample_video_dict)
        self.assertIsNone(res.camera_id, "Descriptor string must resolve to None")

    def test_3_multiple_videos_in_one_response(self):
        """Test that GET /api/v1/videos returns multiple valid videos without validation error."""
        resp = self.client.get("/api/v1/videos", headers=self.headers)
        self.assertEqual(resp.status_code, 200, f"Expected 200, got {resp.status_code}: {resp.text}")
        videos = resp.json()
        self.assertIsInstance(videos, list)
        self.assertGreaterEqual(len(videos), 2, "Expected multiple videos in response")

        for vid in videos:
            cam_id = vid.get("camera_id")
            if cam_id is not None:
                # Must be a valid UUID string
                parsed = uuid.UUID(cam_id)
                self.assertIsInstance(parsed, uuid.UUID)
            else:
                self.assertIsNone(cam_id)

    def test_4_pagination_limit_and_offset(self):
        """Test GET /api/v1/videos with limit=5 and limit=2 pagination."""
        # Test limit=5
        resp_5 = self.client.get("/api/v1/videos?limit=5", headers=self.headers)
        self.assertEqual(resp_5.status_code, 200)
        videos_5 = resp_5.json()
        self.assertLessEqual(len(videos_5), 5)

        # Test limit=2
        resp_2 = self.client.get("/api/v1/videos?limit=2", headers=self.headers)
        self.assertEqual(resp_2.status_code, 200)
        videos_2 = resp_2.json()
        self.assertEqual(len(videos_2), min(2, len(videos_5)))

        # Test offset=1
        if len(videos_5) >= 2:
            resp_offset = self.client.get("/api/v1/videos?limit=1&offset=1", headers=self.headers)
            self.assertEqual(resp_offset.status_code, 200)
            videos_offset = resp_offset.json()
            self.assertEqual(len(videos_offset), 1)
            self.assertEqual(videos_offset[0]["id"], videos_5[1]["id"])

    def test_5_schema_validator_handles_invalid_data_explicitly(self):
        """Test VideoResponse camera_id validation rejects descriptors and converts valid types."""
        test_uuid = uuid.uuid4()
        now = "2026-10-11T20:00:00Z"
        base_payload = {
            "id": uuid.uuid4(),
            "filename": "sample.mp4",
            "original_filename": "sample.mp4",
            "file_path": "storage/sample.mp4",
            "status": "completed",
            "progress_percentage": 100,
            "uploaded_by": uuid.uuid4(),
            "created_at": now
        }

        # 1. Valid UUID instance
        v1 = VideoResponse.model_validate({**base_payload, "camera_id": test_uuid})
        self.assertEqual(v1.camera_id, test_uuid)

        # 2. Valid UUID string
        v2 = VideoResponse.model_validate({**base_payload, "camera_id": str(test_uuid)})
        self.assertEqual(v2.camera_id, test_uuid)

        # 3. None
        v3 = VideoResponse.model_validate({**base_payload, "camera_id": None})
        self.assertIsNone(v3.camera_id)

        # 4. Pydantic Form / FieldInfo descriptor string (The Phase F18 bug trigger)
        desc_str = "annotation=Union[UUID, NoneType] required=False default=None alias='camera_id' json_schema_extra={}"
        v4 = VideoResponse.model_validate({**base_payload, "camera_id": desc_str})
        self.assertIsNone(v4.camera_id, "Descriptor string must be sanitized to None rather than raising error")

        # 5. Arbitrary invalid non-UUID string
        v5 = VideoResponse.model_validate({**base_payload, "camera_id": "not-a-valid-uuid-string"})
        self.assertIsNone(v5.camera_id, "Non-UUID string must be sanitized to None rather than raising error")

        # 6. Object with id (Camera mock)
        class MockCamera:
            id = test_uuid
        v6 = VideoResponse.model_validate({**base_payload, "camera_id": MockCamera()})
        self.assertEqual(v6.camera_id, test_uuid)

if __name__ == "__main__":
    unittest.main()
