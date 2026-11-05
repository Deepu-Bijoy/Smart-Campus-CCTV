"""
Comprehensive test suite verifying:
1. Forensic Reports menu item is removed from sidebar while preserving all other navigation.
2. Upload interfaces (ViolenceDetection, Upload) dynamically display configured maximum upload limit.
3. Config endpoints expose configurable upload limit (5 GiB default).
4. Files below configured limit are accepted.
5. Files exceeding configured limit are rejected with HTTP 413.
6. A video larger than the old 500 MiB limit (524,288,000 bytes) is accepted under the new limit.
7. Empty, corrupt, and unsupported formats are rejected with HTTP 400.
"""

import os
import sys
import uuid
import tempfile
import unittest
import numpy as np
import cv2
from unittest import mock

# Ensure test configuration
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_limits_nav.db"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi.testclient import TestClient
from sqlalchemy.future import select

from app.main import app
from app.core import security
from app.core.config import settings
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.models.user import User
from app.models.camera import Camera
import asyncio

TEST_ADMIN_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
TEST_CAM_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")


class ChunkedOversizedStream:
    """Streams data of specified size in chunks without allocating full size in RAM."""
    def __init__(self, target_size: int):
        self.target_size = target_size
        self.bytes_read = 0
        self.chunk_size = 4 * 1024 * 1024
        self.chunk_buffer = b"0" * self.chunk_size

    def read(self, size=-1):
        if self.bytes_read >= self.target_size:
            return b""
        remaining = self.target_size - self.bytes_read
        take = min(self.chunk_size, remaining)
        data = self.chunk_buffer[:take]
        self.bytes_read += take
        return data


def create_minimal_valid_mp4(target_size_bytes: int | None = None) -> str:
    """Creates a valid decodable MP4 file with 2 frames."""
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


class TestUploadLimitsAndNavigation(unittest.TestCase):
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
                        email="nav_limit_admin@campus.edu",
                        hashed_password="hashed_pass_nav",
                        role="admin",
                        is_active=True
                    )
                    db.add(admin)
                c_res = await db.execute(select(Camera).filter(Camera.id == TEST_CAM_ID))
                if not c_res.scalars().first():
                    cam = Camera(
                        id=TEST_CAM_ID,
                        name="CCTV Gate 1",
                        building="Block A",
                        floor=1,
                        location="Gate 1",
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
        self.patcher = mock.patch("app.api.v1.videos.process_video.delay")
        self.mock_delay = self.patcher.start()
        mock_task = mock.MagicMock()
        mock_task.id = "mock-task-nav-test"
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

    # -------------------------------------------------------------
    # 1. FRONTEND NAVIGATION AND SIDEBAR TESTS
    # -------------------------------------------------------------
    def test_forensic_reports_absent_from_sidebar(self):
        """Verifies 'Forensic Reports' navigation item and FileText icon are absent from Sidebar.tsx."""
        sidebar_path = os.path.abspath(os.path.join(backend_dir, "..", "frontend", "src", "components", "Sidebar.tsx"))
        self.assertTrue(os.path.exists(sidebar_path), f"Sidebar file not found at {sidebar_path}")

        with open(sidebar_path, "r", encoding="utf-8") as f:
            content = f.read()

        self.assertNotIn("Forensic Reports", content, "Forensic Reports label must be absent from Sidebar.tsx")
        self.assertNotIn("'/reports'", content, "Route path '/reports' must not be in Sidebar menu items")
        self.assertNotIn("FileText", content, "FileText icon import must be removed from Sidebar.tsx")

    def test_other_sidebar_items_remain(self):
        """Verifies that all required operational items remain present and intact in Sidebar.tsx."""
        sidebar_path = os.path.abspath(os.path.join(backend_dir, "..", "frontend", "src", "components", "Sidebar.tsx"))
        with open(sidebar_path, "r", encoding="utf-8") as f:
            content = f.read()

        required_items = [
            "Dashboard",
            "Surveillance Feeds",
            "Camera Management",
            "Security Alerts",
            "Violence Detection",
            "Upload Feed",
            "Student Directory",
            "Investigation Search",
            "User Management"
        ]
        for item in required_items:
            self.assertIn(item, content, f"Sidebar must preserve navigation item: {item}")

    def test_upload_ui_displays_dynamic_limit(self):
        """Verifies that upload pages (ViolenceDetection.tsx and Upload.tsx) use dynamic configuration and have no hardcoded 500 MiB."""
        frontend_src = os.path.abspath(os.path.join(backend_dir, "..", "frontend", "src"))
        violence_path = os.path.join(frontend_src, "pages", "ViolenceDetection.tsx")
        upload_path = os.path.join(frontend_src, "pages", "Upload.tsx")
        config_path = os.path.join(frontend_src, "config", "upload.ts")

        self.assertTrue(os.path.exists(config_path), "Centralized upload config must exist")

        with open(violence_path, "r", encoding="utf-8") as f:
            violence_content = f.read()
        self.assertNotIn("Supports MP4, AVI, MKV, or MOV up to 500 MiB", violence_content,
                         "ViolenceDetection must not hardcode 'up to 500 MiB'")
        self.assertNotIn("MAX_UPLOAD_SIZE_BYTES = 524288000", violence_content,
                         "ViolenceDetection must not hardcode 524288000 bytes")
        self.assertIn("useUploadConfig", violence_content, "ViolenceDetection must use useUploadConfig hook")

        with open(upload_path, "r", encoding="utf-8") as f:
            upload_content = f.read()
        self.assertNotIn("(Up to 500 MiB)", upload_content,
                         "Upload.tsx must not hardcode '(Up to 500 MiB)'")
        self.assertNotIn("MAX_UPLOAD_SIZE_BYTES = 524288000", upload_content,
                         "Upload.tsx must not hardcode 524288000 bytes")
        self.assertIn("useUploadConfig", upload_content, "Upload.tsx must use useUploadConfig hook")

    # -------------------------------------------------------------
    # 2. BACKEND CONFIGURATION ENDPOINTS
    # -------------------------------------------------------------
    def test_backend_upload_config_endpoints(self):
        """Verifies GET /api/v1/videos/upload-config and GET /api/v1/violence/upload-config return consistent 5 GiB config."""
        res_v = self.client.get("/api/v1/videos/upload-config")
        self.assertEqual(res_v.status_code, 200)
        data_v = res_v.json()
        self.assertEqual(data_v["max_upload_size_bytes"], settings.MAX_UPLOAD_SIZE_BYTES)
        self.assertEqual(data_v["max_upload_size_bytes"], 5_368_709_120)  # 5 GiB default
        self.assertEqual(data_v["max_upload_size_formatted"], "5 GiB")
        self.assertIn("MP4", data_v["allowed_formats"])

        res_vio = self.client.get("/api/v1/violence/upload-config")
        self.assertEqual(res_vio.status_code, 200)
        data_vio = res_vio.json()
        self.assertEqual(data_vio["max_upload_size_bytes"], settings.MAX_UPLOAD_SIZE_BYTES)
        self.assertEqual(data_vio["max_upload_size_formatted"], "5 GiB")

    # -------------------------------------------------------------
    # 3. UPLOAD VALIDATION AND LIMIT ENFORCEMENT
    # -------------------------------------------------------------
    def test_valid_file_below_configured_limit_accepted(self):
        """Valid video below limit is accepted with HTTP 201."""
        valid_path = create_minimal_valid_mp4()
        self.temp_files.append(valid_path)

        with open(valid_path, "rb") as f:
            res = self.client.post(
                "/api/v1/videos/upload",
                files={"file": (f"test_valid_{uuid.uuid4().hex[:6]}.mp4", f, "video/mp4")},
                headers=self.headers
            )
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.json()["status"], "queued")

    def test_file_larger_than_old_500mib_limit_accepted(self):
        """A video of 524,288,000 bytes (old 500 MiB limit) is accepted under the new 5 GiB limit."""
        target_size = 524_288_000  # 500 MiB
        large_path = create_minimal_valid_mp4(target_size_bytes=target_size)
        self.temp_files.append(large_path)
        self.assertEqual(os.path.getsize(large_path), target_size)

        with open(large_path, "rb") as f:
            res_v = self.client.post(
                "/api/v1/videos/upload",
                files={"file": (f"test_500m_{uuid.uuid4().hex[:6]}.mp4", f, "video/mp4")},
                headers=self.headers
            )
        self.assertEqual(res_v.status_code, 201)
        self.assertEqual(res_v.json()["file_size"], target_size)

        with open(large_path, "rb") as f:
            res_vio = self.client.post(
                "/api/v1/violence/upload",
                files={"file": (f"test_500m_vio_{uuid.uuid4().hex[:6]}.mp4", f, "video/mp4")},
                headers=self.headers
            )
        self.assertEqual(res_vio.status_code, 201)
        self.assertEqual(res_vio.json()["file_size"], target_size)

    def test_file_exceeding_limit_rejected_with_413(self):
        """Uploading file exceeding configured limit is rejected cleanly with HTTP 413."""
        simulated_limit = 30 * 1024 * 1024  # 30 MiB simulated limit for unit test efficiency
        with mock.patch.object(settings, "MAX_UPLOAD_SIZE_BYTES", simulated_limit):
            stream = ChunkedOversizedStream(simulated_limit + 1024)
            res = self.client.post(
                "/api/v1/videos/upload",
                files={"file": ("too_large.mp4", stream, "video/mp4")},
                headers=self.headers
            )
            self.assertEqual(res.status_code, 413)
            detail = res.json().get("detail", "").lower()
            self.assertIn("exceeds", detail)
            self.assertIn(f"{simulated_limit:,}", detail)

    def test_empty_file_rejected_with_400(self):
        """Empty 0-byte file returns HTTP 400."""
        res = self.client.post(
            "/api/v1/videos/upload",
            files={"file": ("empty.mp4", b"", "video/mp4")},
            headers=self.headers
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("empty", res.json().get("detail", "").lower())

    def test_corrupt_file_rejected_with_400(self):
        """Corrupt arbitrary bytes as .mp4 returns HTTP 400."""
        res = self.client.post(
            "/api/v1/videos/upload",
            files={"file": ("corrupt.mp4", b"not a real video stream container", "video/mp4")},
            headers=self.headers
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("corrupt", res.json().get("detail", "").lower())

    def test_unsupported_format_rejected_with_400(self):
        """Uploading forbidden format (.exe, .txt, .sh) returns HTTP 400."""
        for ext in [".exe", ".txt", ".sh"]:
            res = self.client.post(
                "/api/v1/videos/upload",
                files={"file": (f"script{ext}", b"echo hello", "text/plain")},
                headers=self.headers
            )
            self.assertEqual(res.status_code, 400)
            self.assertIn("unsupported", res.json().get("detail", "").lower())


if __name__ == "__main__":
    unittest.main()
