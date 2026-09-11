import asyncio
import os
import sys
import uuid
import tempfile
import cv2
import numpy as np
from unittest.mock import MagicMock

# Set fallback environment flags before imports
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_violence_upload.db"

# Mock out heavy deep learning models before backend imports
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['insightface'] = MagicMock()
sys.modules['insightface.app'] = MagicMock()

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from fastapi import status
from app.main import app
from app.api import deps
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.models.user import User

client = TestClient(app)

async def init_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

def create_dummy_mp4(filepath: str, num_frames=15, width=320, height=240, fps=15.0):
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filepath, fourcc, fps, (width, height))
    for i in range(num_frames):
        frame = np.full((height, width, 3), (i * 15) % 255, dtype=np.uint8)
        cv2.putText(frame, f"Frame {i}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
        out.write(frame)
    out.release()

def test_violence_video_upload_suite():
    print("\n=======================================================")
    print("  RUNNING VIOLENCE DETECTION VIDEO UPLOAD TEST SUITE")
    print("=======================================================")
    asyncio.run(init_test_db())

    # Setup mock user dependency override
    mock_user_id = uuid.uuid4()
    mock_user = User(
        id=mock_user_id,
        email="operator@smartcampus.com",
        hashed_password="fakehashedpassword",
        full_name="Lead Security Officer",
        is_active=True
    )
    app.dependency_overrides[deps.get_current_user] = lambda: mock_user

    async def get_test_db():
        async with SessionLocal() as session:
            yield session
    app.dependency_overrides[deps.get_db] = get_test_db

    # Test 1: Valid Video Upload
    print("\n[TEST 1] Uploading valid CCTV footage (.mp4)...")
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_file:
        tmp_path = tmp_file.name
    try:
        create_dummy_mp4(tmp_path, num_frames=30, width=320, height=240, fps=15.0)
        with open(tmp_path, "rb") as f:
            response = client.post(
                "/api/v1/violence/upload",
                data={"title": "Campus Quad Angle 1"},
                files={"file": ("quad_feed.mp4", f, "video/mp4")}
            )
        assert response.status_code == status.HTTP_201_CREATED, f"Expected 201, got {response.status_code}: {response.text}"
        data = response.json()
        assert "video_id" in data
        assert data["original_filename"] == "quad_feed.mp4"
        assert data["status"] == "uploaded"
        assert data["duration"] is not None and data["duration"] > 0
        assert data["width"] == 320
        assert data["height"] == 240
        assert "file_url" in data
        print(f"  --> PASSED: Video ID: {data['video_id']} | Duration: {data['duration']}s | Resolution: {data['width']}x{data['height']}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

    # Test 2: Invalid File Extension
    print("\n[TEST 2] Uploading invalid file extension (.txt)...")
    response = client.post(
        "/api/v1/violence/upload",
        files={"file": ("notes.txt", b"This is a text file", "text/plain")}
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400, got {response.status_code}"
    assert "Unsupported video format" in response.json()["detail"]
    print(f"  --> PASSED: Correctly rejected invalid extension with detail: {response.json()['detail']}")

    # Test 3: Empty File (0 Bytes)
    print("\n[TEST 3] Uploading empty video (0 bytes)...")
    response = client.post(
        "/api/v1/violence/upload",
        files={"file": ("empty.mp4", b"", "video/mp4")}
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400, got {response.status_code}"
    assert "empty" in response.json()["detail"].lower()
    print(f"  --> PASSED: Correctly rejected 0-byte video with detail: {response.json()['detail']}")

    # Test 4: Corrupted Video (Invalid stream bytes with .mp4 extension)
    print("\n[TEST 4] Uploading corrupted video (fake bytes)...")
    corrupt_bytes = b"CORRUPTED_VIDEO_HEADER_RANDOM_DATA_1234567890" * 20
    response = client.post(
        "/api/v1/violence/upload",
        files={"file": ("corrupt.mp4", corrupt_bytes, "video/mp4")}
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST, f"Expected 400, got {response.status_code}"
    assert "corrupt" in response.json()["detail"].lower() or "unreadable" in response.json()["detail"].lower()
    print(f"  --> PASSED: Correctly caught corrupted video stream with detail: {response.json()['detail']}")

    # Test 5: Oversized Video (> 100MB limit)
    print("\n[TEST 5] Testing oversized video guard (> 100MB)...")
    class LargeDummyFile:
        def __init__(self, size=102 * 1024 * 1024):
            self.remaining = size
        def read(self, chunk_size=-1):
            if self.remaining <= 0:
                return b""
            if chunk_size is None or chunk_size < 0:
                amt = min(self.remaining, 1024 * 1024)
            else:
                amt = min(self.remaining, chunk_size)
            self.remaining -= amt
            return b"X" * amt
        def seek(self, *args):
            return 0
        def tell(self):
            return 0

    response = client.post(
        "/api/v1/violence/upload",
        files={"file": ("huge_cctv.mp4", LargeDummyFile(), "video/mp4")}
    )
    assert response.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"Expected 413, got {response.status_code}: {response.text}"
    assert "100mb" in response.json()["detail"].lower()
    print(f"  --> PASSED: Correctly enforced 100MB limit with HTTP 413: {response.json()['detail']}")

    print("\n=======================================================")
    print("  ALL 5 UPLOAD VALIDATION TESTS PASSED SUCCESSFULLY!")
    print("=======================================================\n")

if __name__ == "__main__":
    test_violence_video_upload_suite()
