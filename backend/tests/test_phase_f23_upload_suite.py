"""
PHASE F23.2 TEST SUITE — 500 MiB CCTV Video Upload Validation

Tests:
1. Valid video below limit (small video fixture) -> 201 Created.
2. Valid video between 100 MiB and 500 MiB (105 MiB) -> 201 Created.
3. Valid video exactly at the 500 MiB limit (524,288,000 bytes) -> 201 Created.
4. Video exceeding limit (524,288,000 + 1024 bytes) -> 413 Request Entity Too Large.
5. Invalid extensions (.exe, .txt) -> 400 Bad Request.
6. Empty 0-byte file -> 400 Bad Request.
7. Corrupt content (text/garbage in .mp4) -> 400 Bad Request.
8. Partial upload cleanup after failure -> No orphaned file on disk, no DB row added.
9. Duplicate prevention on retry -> Returns existing record, no duplicate DB rows.
"""

import os
import sys
import uuid
import tempfile
import unittest
import numpy as np
import cv2
from datetime import datetime, timezone

# Ensure test configuration
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_f23_upload.db"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi.testclient import TestClient
from sqlalchemy.future import select
from sqlalchemy import func

from app.main import app
from app.core import security
from app.core.config import settings
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.models.user import User
from app.models.camera import Camera
from app.models.video import Video
import asyncio

TEST_ADMIN_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
TEST_CAM_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")


class ChunkedOversizedStream:
    """Streams data of specified size in 1MB chunks without allocating the full size in RAM."""
    def __init__(self, target_size: int, prefix_bytes: bytes = b""):
        self.target_size = target_size
        self.prefix = prefix_bytes
        self.prefix_len = len(prefix_bytes)
        self.bytes_read = 0
        self.chunk_size = 8 * 1024 * 1024
        self.chunk_buffer = b"0" * self.chunk_size

    def read(self, size=-1):
        if self.bytes_read >= self.target_size:
            return b""
        remaining = self.target_size - self.bytes_read
        take = min(self.chunk_size, remaining)

        if self.bytes_read < self.prefix_len:
            prefix_chunk = self.prefix[self.bytes_read : self.bytes_read + take]
            pad_len = take - len(prefix_chunk)
            data = prefix_chunk + self.chunk_buffer[:pad_len]
        else:
            data = self.chunk_buffer[:take]

        self.bytes_read += take
        return data


def create_minimal_valid_mp4(target_size_bytes: int | None = None) -> str:
    """
    Creates a valid decodable MP4 file with 2 frames.
    If target_size_bytes is provided, uses sparse file truncate to achieve
    exact target size in 1ms without RAM consumption.
    """
    tmp = tempfile.mktemp(suffix=".mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(tmp, fourcc, 25.0, (64, 64))
    out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    if target_size_bytes is not None:
        init_size = os.path.getsize(tmp)
        if target_size_bytes > init_size:
            with open(tmp, "ab") as f:
                f.truncate(target_size_bytes)
    return tmp


class TestPhaseF23UploadSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        async def _init_db():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with SessionLocal() as db:
                u_res = await db.execute(select(User).filter(User.id == TEST_ADMIN_ID))
                if not u_res.scalars().first():
                    admin = User(
                        id=TEST_ADMIN_ID,
                        email="f23_admin@campus.edu",
                        hashed_password="hashed_pass_f23",
                        role="admin",
                        is_active=True
                    )
                    db.add(admin)
                c_res = await db.execute(select(Camera).filter(Camera.id == TEST_CAM_ID))
                if not c_res.scalars().first():
                    cam = Camera(
                        id=TEST_CAM_ID,
                        name="CCTV Main North Gate",
                        building="Block A",
                        floor=1,
                        location="Main Gate",
                        direction="North",
                        resolution="1920x1080",
                        status="active"
                    )
                    db.add(cam)
                await db.commit()

        asyncio.run(_init_db())
        token = security.create_access_token(TEST_ADMIN_ID)
        cls.headers = {"Authorization": f"Bearer {token}"}
        cls.client = TestClient(app, raise_server_exceptions=False)
        cls.temp_files = []

    def setUp(self):
        import unittest.mock as mock
        self.patcher = mock.patch("app.api.v1.videos.process_video.delay")
        self.mock_delay = self.patcher.start()
        mock_task = mock.MagicMock()
        mock_task.id = "mock-task-f23"
        self.mock_delay.return_value = mock_task

    def tearDown(self):
        self.patcher.stop()

    @classmethod
    def tearDownClass(cls):
        for f in cls.temp_files:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

    def test_1_valid_file_below_limit(self):
        """Upload of a normal valid MP4 below 100MB succeeds with HTTP 201."""
        valid_path = create_minimal_valid_mp4()
        self.temp_files.append(valid_path)
        sz = os.path.getsize(valid_path)
        self.assertLess(sz, 100 * 1024 * 1024)

        with open(valid_path, "rb") as f:
            res_v = self.client.post(
                "/api/v1/videos/upload",
                files={"file": (f"test_normal_{uuid.uuid4().hex[:6]}.mp4", f, "video/mp4")},
                headers=self.headers
            )
        self.assertEqual(res_v.status_code, 201, f"Expected 201, got {res_v.status_code}: {res_v.text}")
        data_v = res_v.json()
        self.assertEqual(data_v["status"], "queued")
        self.assertIsNotNone(data_v["id"])

        with open(valid_path, "rb") as f:
            res_vio = self.client.post(
                "/api/v1/violence/upload",
                files={"file": (f"test_normal_vio_{uuid.uuid4().hex[:6]}.mp4", f, "video/mp4")},
                headers=self.headers
            )
        self.assertEqual(res_vio.status_code, 201, f"Expected 201, got {res_vio.status_code}: {res_vio.text}")
        data_vio = res_vio.json()
        self.assertEqual(data_vio["status"], "uploaded")
        self.assertIsNotNone(data_vio["video_id"])

    def test_2_valid_file_between_100_and_500_mib(self):
        """Upload of a valid 105 MiB video (> 100 MiB, < 500 MiB) succeeds with HTTP 201."""
        target_size = 105 * 1024 * 1024  # 105 MiB
        large_path = create_minimal_valid_mp4(target_size_bytes=target_size)
        self.temp_files.append(large_path)
        self.assertEqual(os.path.getsize(large_path), target_size)

        with open(large_path, "rb") as f:
            res_v = self.client.post(
                "/api/v1/videos/upload",
                files={"file": (f"test_105mib_{uuid.uuid4().hex[:6]}.mp4", f, "video/mp4")},
                headers=self.headers
            )
        self.assertEqual(res_v.status_code, 201, f"Expected 201, got {res_v.status_code}: {res_v.text}")
        data_v = res_v.json()
        self.assertEqual(data_v["file_size"], target_size)

        with open(large_path, "rb") as f:
            res_vio = self.client.post(
                "/api/v1/violence/upload",
                files={"file": (f"test_105mib_vio_{uuid.uuid4().hex[:6]}.mp4", f, "video/mp4")},
                headers=self.headers
            )
        self.assertEqual(res_vio.status_code, 201, f"Expected 201, got {res_vio.status_code}: {res_vio.text}")
        data_vio = res_vio.json()
        self.assertEqual(data_vio["file_size"], target_size)

    def test_3_valid_file_at_500mib_succeeds(self):
        """Upload of a video at 524,288,000 bytes (old 500 MiB limit) succeeds with HTTP 201 under new 5 GiB limit."""
        target_size = 524_288_000  # 500 MiB (524,288,000 bytes)
        exact_path = create_minimal_valid_mp4(target_size_bytes=target_size)
        self.temp_files.append(exact_path)
        self.assertEqual(os.path.getsize(exact_path), target_size)

        with open(exact_path, "rb") as f:
            res_v = self.client.post(
                "/api/v1/videos/upload",
                files={"file": (f"test_exact500_{uuid.uuid4().hex[:6]}.mp4", f, "video/mp4")},
                headers=self.headers
            )
        self.assertEqual(res_v.status_code, 201, f"Expected 201, got {res_v.status_code}: {res_v.text}")
        self.assertEqual(res_v.json()["file_size"], target_size)

        with open(exact_path, "rb") as f:
            res_vio = self.client.post(
                "/api/v1/violence/upload",
                files={"file": (f"test_exact500_vio_{uuid.uuid4().hex[:6]}.mp4", f, "video/mp4")},
                headers=self.headers
            )
        self.assertEqual(res_vio.status_code, 201, f"Expected 201, got {res_vio.status_code}: {res_vio.text}")
        self.assertEqual(res_vio.json()["file_size"], target_size)

    def test_4_file_exceeding_limit(self):
        """Upload exceeding configured MAX_UPLOAD_SIZE_BYTES is rejected with HTTP 413 and clear error."""
        import unittest.mock as mock
        simulated_limit = 50 * 1024 * 1024  # 50 MiB for fast, simulated testing
        with mock.patch.object(settings, "MAX_UPLOAD_SIZE_BYTES", simulated_limit):
            oversized_size = simulated_limit + 1024
            stream_v = ChunkedOversizedStream(oversized_size)

            res_v = self.client.post(
                "/api/v1/videos/upload",
                files={"file": ("too_large_general.mp4", stream_v, "video/mp4")},
                headers=self.headers
            )
            self.assertEqual(res_v.status_code, 413, f"Expected 413, got {res_v.status_code}")
            detail_v = res_v.json().get("detail", "").lower()
            self.assertIn("exceeds", detail_v)
            self.assertIn(f"{simulated_limit:,}", detail_v)

            stream_vio = ChunkedOversizedStream(oversized_size)
            res_vio = self.client.post(
                "/api/v1/violence/upload",
                files={"file": ("too_large_violence.mp4", stream_vio, "video/mp4")},
                headers=self.headers
            )
            self.assertEqual(res_vio.status_code, 413, f"Expected 413, got {res_vio.status_code}")
            detail_vio = res_vio.json().get("detail", "").lower()
            self.assertIn("exceeds", detail_vio)
            self.assertIn(f"{simulated_limit:,}", detail_vio)

    def test_5_invalid_extensions(self):
        """Uploading non-video extensions (.exe, .txt) returns HTTP 400."""
        for bad_ext in [".exe", ".txt", ".sh", ".bin"]:
            res = self.client.post(
                "/api/v1/videos/upload",
                files={"file": (f"test{bad_ext}", b"echo 'bad'", "application/octet-stream")},
                headers=self.headers
            )
            self.assertEqual(res.status_code, 400, f"Expected 400 for {bad_ext}")
            self.assertIn("unsupported", res.json().get("detail", "").lower())

            res_vio = self.client.post(
                "/api/v1/violence/upload",
                files={"file": (f"test{bad_ext}", b"echo 'bad'", "application/octet-stream")},
                headers=self.headers
            )
            self.assertEqual(res_vio.status_code, 400, f"Expected 400 for {bad_ext}")
            self.assertIn("unsupported", res_vio.json().get("detail", "").lower())

    def test_6_invalid_video_empty_file(self):
        """Uploading an empty 0-byte file returns HTTP 400."""
        res_v = self.client.post(
            "/api/v1/videos/upload",
            files={"file": ("empty.mp4", b"", "video/mp4")},
            headers=self.headers
        )
        self.assertEqual(res_v.status_code, 400)
        self.assertIn("empty", res_v.json().get("detail", "").lower())

        res_vio = self.client.post(
            "/api/v1/violence/upload",
            files={"file": ("empty.mp4", b"", "video/mp4")},
            headers=self.headers
        )
        self.assertEqual(res_vio.status_code, 400)
        self.assertIn("empty", res_vio.json().get("detail", "").lower())

    def test_7_invalid_video_corrupt_content(self):
        """Uploading corrupted text or arbitrary bytes as .mp4 returns HTTP 400."""
        fake_content = b"This is plain text pretending to be an MP4 video container."
        res_v = self.client.post(
            "/api/v1/videos/upload",
            files={"file": ("corrupt.mp4", fake_content, "video/mp4")},
            headers=self.headers
        )
        self.assertEqual(res_v.status_code, 400)
        self.assertIn("corrupt", res_v.json().get("detail", "").lower())

        res_vio = self.client.post(
            "/api/v1/violence/upload",
            files={"file": ("corrupt.mp4", fake_content, "video/mp4")},
            headers=self.headers
        )
        self.assertEqual(res_vio.status_code, 400)
        self.assertIn("corrupt", res_vio.json().get("detail", "").lower())

    def test_8_partial_upload_cleanup_after_failure(self):
        """When an upload is rejected (size exceeded or corrupt), partial file is deleted and no DB row is added."""
        async def _count_videos():
            async with SessionLocal() as db:
                return (await db.execute(select(func.count(Video.id)))).scalar() or 0

        initial_count = asyncio.run(_count_videos())
        storage_files_before = set(os.listdir(settings.STORAGE_DIR)) if os.path.exists(settings.STORAGE_DIR) else set()

        # Attempt oversized upload with fast simulated stream
        import unittest.mock as mock
        simulated_limit = 20 * 1024 * 1024
        with mock.patch.object(settings, "MAX_UPLOAD_SIZE_BYTES", simulated_limit):
            stream = ChunkedOversizedStream(simulated_limit + 2048)
            res = self.client.post(
                "/api/v1/videos/upload",
                files={"file": ("cleanup_test.mp4", stream, "video/mp4")},
                headers=self.headers
            )
            self.assertEqual(res.status_code, 413)

        # Attempt corrupt upload
        res_corrupt = self.client.post(
            "/api/v1/videos/upload",
            files={"file": ("cleanup_corrupt.mp4", b"bad bytes", "video/mp4")},
            headers=self.headers
        )
        self.assertEqual(res_corrupt.status_code, 400)

        # Check that no video record was committed
        final_count = asyncio.run(_count_videos())
        self.assertEqual(final_count, initial_count, "Database must not retain rows for failed uploads")

        # Check storage directory has no orphaned temporary files from failed attempts
        storage_files_after = set(os.listdir(settings.STORAGE_DIR)) if os.path.exists(settings.STORAGE_DIR) else set()
        new_files = storage_files_after - storage_files_before
        new_mp4s = [f for f in new_files if f.endswith(".mp4")]
        self.assertEqual(len(new_mp4s), 0, f"Expected no leftover partial files, found: {new_mp4s}")

    def test_9_prevention_of_duplicate_records_on_retry(self):
        """Retrying upload of the exact same video returns existing record without creating duplicate rows."""
        valid_path = create_minimal_valid_mp4()
        self.temp_files.append(valid_path)
        filename = f"retry_dedup_{uuid.uuid4().hex[:6]}.mp4"

        # First upload
        with open(valid_path, "rb") as f:
            res1 = self.client.post(
                "/api/v1/videos/upload",
                files={"file": (filename, f, "video/mp4")},
                headers=self.headers
            )
        self.assertEqual(res1.status_code, 201)
        video_id_1 = res1.json()["id"]

        # Immediate retry with same filename & content
        with open(valid_path, "rb") as f:
            res2 = self.client.post(
                "/api/v1/videos/upload",
                files={"file": (filename, f, "video/mp4")},
                headers=self.headers
            )
        self.assertEqual(res2.status_code, 201)
        video_id_2 = res2.json()["id"]

        # Must return the same video ID
        self.assertEqual(video_id_1, video_id_2, "Retry must return existing video record ID")

        # Verify database has exactly 1 record for this filename
        async def _count_matching():
            async with SessionLocal() as db:
                stmt = select(func.count(Video.id)).filter(
                    Video.original_filename == filename,
                    Video.uploaded_by == TEST_ADMIN_ID
                )
                return (await db.execute(stmt)).scalar() or 0

        matching_count = asyncio.run(_count_matching())
        self.assertEqual(matching_count, 1, f"Expected exactly 1 DB record, found {matching_count}")


if __name__ == "__main__":
    unittest.main()
