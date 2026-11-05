import os
import sys
import uuid
import io
import time
import shutil
import tempfile
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

import pytest
import cv2
import numpy as np
import torch
from fastapi.testclient import TestClient

# Ensure test isolation
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_resilience_audit.db"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.main import app
from app.core import security
from app.core.config import settings
from app.api import deps
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.models.user import User
from app.models.camera import Camera
from app.models.video import Video
from app.models.incident import Incident, Evidence, DetectedEvent
from app.models.report import Report
from app.models.student import Student
from app.api.v1.violence import check_video_integrity
from app.services.video_metadata import extract_video_metadata
from app.services.vector_store import QdrantVectorStore
from app.pipeline.video_reader import VideoReader
from app.pipeline.x3d_violence_detector import X3DViolenceDetector
from app.tasks.video_tasks import process_video

# Use raise_server_exceptions=False so we can assert actual HTTP 500 responses
client = TestClient(app, raise_server_exceptions=False)

# UUIDs MUST contain hex characters ('a'-'f') to prevent SQLite dynamic column affinity
# from coercing pure-digit UUID strings into scientific notation float values.
ADMIN_USER_ID = uuid.UUID("11111111-aaaa-1111-aaaa-111111111111")
OPERATOR_USER_ID = uuid.UUID("22222222-bbbb-2222-bbbb-222222222222")
TEST_CAM_ID = uuid.UUID("33333333-cccc-3333-cccc-333333333333")

async def setup_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        admin = User(
            id=ADMIN_USER_ID,
            email="admin@resilience.audit",
            hashed_password=security.get_password_hash("AuditAdminPass123!"),
            full_name="Admin Resilience Auditor",
            role="admin",
            is_active=True
        )
        operator = User(
            id=OPERATOR_USER_ID,
            email="operator@resilience.audit",
            hashed_password=security.get_password_hash("AuditOpPass123!"),
            full_name="Operator Resilience Auditor",
            role="operator",
            is_active=True
        )
        cam = Camera(
            id=TEST_CAM_ID,
            name="Auditor Camera 1",
            building="Safety Block",
            floor=1,
            location="Main Gate",
            direction="North",
            resolution="1080p",
            status="active"
        )
        db.add_all([admin, operator, cam])
        await db.commit()

def run_async(coro):
    return asyncio.run(coro)

run_async(setup_test_db())

def get_auth_headers(user_id: uuid.UUID) -> dict:
    token = security.create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}

@pytest.fixture
def admin_headers():
    return get_auth_headers(ADMIN_USER_ID)

@pytest.fixture
def operator_headers():
    return get_auth_headers(OPERATOR_USER_ID)

@pytest.fixture
def dummy_mp4_bytes():
    """Generates a small valid MP4 in-memory"""
    temp_p = tempfile.mktemp(suffix=".mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_p, fourcc, 25.0, (64, 64))
    for _ in range(25):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()
    with open(temp_p, "rb") as f:
        data = f.read()
    if os.path.exists(temp_p):
        os.remove(temp_p)
    return data

# =========================================================================
# STEP 1: Baseline Environment Assertions
# =========================================================================

def test_env_baseline_components():
    """Verify runtime environment versions and hardware state."""
    import fastapi, sqlalchemy
    assert sys.version_info >= (3, 10), "Python version must be >= 3.10"
    assert fastapi.__version__ is not None
    assert sqlalchemy.__version__ is not None
    assert torch.__version__ is not None
    # PyTorch and CUDA availability check
    cuda_avail = torch.cuda.is_available()
    assert isinstance(cuda_avail, bool)
    # Check FFmpeg available
    assert shutil.which("ffmpeg") is not None or os.path.exists(r"C:\Users\Asus\.local\bin\ffmpeg.EXE")

# =========================================================================
# STEP 2: Invalid Video Inputs
# =========================================================================

def test_invalid_video_zero_byte_violence_upload(operator_headers):
    """Uploading 0-byte video to /violence/upload returns 400 and cleans up file."""
    res = client.post(
        "/api/v1/violence/upload",
        files={"file": ("zero.mp4", b"", "video/mp4")},
        headers=operator_headers
    )
    assert res.status_code == 400
    assert "empty" in res.json()["detail"].lower()

def test_invalid_video_zero_byte_general_upload(operator_headers):
    """Uploading 0-byte video to /videos/upload."""
    res = client.post(
        "/api/v1/videos/upload",
        files={"file": ("zero.mp4", b"", "video/mp4")},
        headers=operator_headers
    )
    # General /videos/upload accepts file and sets duration to 0.0 in metadata
    assert res.status_code == 201
    assert res.json()["file_size"] == 0

def test_invalid_video_corrupted_mp4_violence_upload(operator_headers):
    """Uploading corrupted bytes with MP4 extension returns 400."""
    corrupted_data = b"NOT_A_VALID_MP4_HEADER_GARBAGE_PAYLOAD_FOR_TESTING"
    res = client.post(
        "/api/v1/violence/upload",
        files={"file": ("corrupt.mp4", corrupted_data, "video/mp4")},
        headers=operator_headers
    )
    assert res.status_code == 400
    assert "corrupt" in res.json()["detail"].lower()

def test_invalid_video_truncated_mp4_violence_upload(operator_headers):
    """Uploading truncated MP4 container returns 400."""
    truncated_data = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00isommp42"
    res = client.post(
        "/api/v1/violence/upload",
        files={"file": ("truncated.mp4", truncated_data, "video/mp4")},
        headers=operator_headers
    )
    assert res.status_code == 400
    assert "corrupt" in res.json()["detail"].lower()

def test_invalid_video_fake_container_text_file(operator_headers):
    """Uploading plain text file disguised as .mp4 returns 400."""
    text_data = b"Plain text contents pretending to be video container."
    res = client.post(
        "/api/v1/violence/upload",
        files={"file": ("fake_video.mp4", text_data, "video/mp4")},
        headers=operator_headers
    )
    assert res.status_code == 400
    assert "corrupt" in res.json()["detail"].lower()

def test_invalid_video_unsupported_extension(operator_headers):
    """Uploading executable or unsupported file extension returns 400."""
    exe_data = b"MZ\x90\x00\x03\x00"
    res = client.post(
        "/api/v1/violence/upload",
        files={"file": ("malware.exe", exe_data, "application/octet-stream")},
        headers=operator_headers
    )
    assert res.status_code == 400
    assert "unsupported" in res.json()["detail"].lower()

def test_invalid_video_oversized_file(operator_headers):
    """Uploading file exceeding MAX_UPLOAD_SIZE_BYTES is rejected with 413."""
    from app.core.config import settings

    class ChunkedOversizedStream:
        def __init__(self, target_size: int):
            self.target_size = target_size
            self.bytes_read = 0
            self.chunk = b"0" * (1024 * 1024)
        def read(self, size=-1):
            if self.bytes_read >= self.target_size:
                return b""
            rem = self.target_size - self.bytes_read
            take = min(len(self.chunk), rem)
            self.bytes_read += take
            return self.chunk[:take]

    res = client.post(
        "/api/v1/violence/upload",
        files={"file": ("too_large.mp4", ChunkedOversizedStream(settings.MAX_UPLOAD_SIZE_BYTES + 1024), "video/mp4")},
        headers=operator_headers
    )
    assert res.status_code == 413
    assert "exceeds" in res.json()["detail"].lower()

def test_invalid_video_extremely_short_integrity():
    """Video with only 2 frames passes stream integrity with small duration."""
    temp_p = tempfile.mktemp(suffix=".mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_p, fourcc, 25.0, (64, 64))
    out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    is_valid, err = check_video_integrity(temp_p)
    meta = extract_video_metadata(temp_p)
    if os.path.exists(temp_p):
        os.remove(temp_p)

    assert is_valid is True
    assert meta["duration"] > 0
    assert meta["fps"] == 25.0

def test_invalid_video_fewer_than_16_frames_x3d():
    """X3D-M gracefully handles video with <16 frames by interpolating slices."""
    temp_p = tempfile.mktemp(suffix=".mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_p, fourcc, 25.0, (64, 64))
    for _ in range(5):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    detector = X3DViolenceDetector()
    result = detector.detect_violence(temp_p)
    if os.path.exists(temp_p):
        os.remove(temp_p)

    assert result.total_frames == 5
    assert len(result.windows) >= 1
    assert result.verdict is not None

def test_invalid_video_unusual_fps():
    """Video with 0.5 FPS extracts valid duration and frames without division by zero."""
    temp_p = tempfile.mktemp(suffix=".mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_p, fourcc, 0.5, (64, 64))
    for _ in range(3):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    meta = extract_video_metadata(temp_p)
    reader = VideoReader(temp_p, target_fps=5.0)
    frames = list(reader.read_frames())
    if os.path.exists(temp_p):
        os.remove(temp_p)

    assert meta["fps"] == 0.5
    assert len(frames) == 3

def test_invalid_video_zero_fps_videoreader():
    """VideoReader with non-existent or 0 FPS file terminates gracefully."""
    reader = VideoReader("nonexistent_path_test.mp4", target_fps=5.0)
    frames = list(reader.read_frames())
    assert len(frames) == 0

# =========================================================================
# STEP 3: Missing Files / Disappearing Resources
# =========================================================================

def test_missing_video_id_violence_analyze(operator_headers):
    """Calling /violence/analyze with non-existent video_id returns 404."""
    non_existent_id = uuid.uuid4()
    res = client.post(
        "/api/v1/violence/analyze",
        data={"video_id": str(non_existent_id)},
        headers=operator_headers
    )
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()

def test_missing_video_status(operator_headers):
    """Calling /violence/status with non-existent video_id returns 404."""
    res = client.get(f"/api/v1/violence/status/{uuid.uuid4()}", headers=operator_headers)
    assert res.status_code == 404

def test_missing_camera_resource(operator_headers):
    """Requesting non-existent camera returns 404."""
    res = client.get(f"/api/v1/cameras/{uuid.uuid4()}", headers=operator_headers)
    assert res.status_code == 404

def test_missing_incident_resource(operator_headers):
    """Requesting non-existent incident returns 404."""
    res = client.get(f"/api/v1/investigations/incidents/{uuid.uuid4()}", headers=operator_headers)
    assert res.status_code == 404

def test_missing_student_resource(operator_headers):
    """Requesting non-existent student returns 404."""
    res = client.get(f"/api/v1/students/{uuid.uuid4()}", headers=operator_headers)
    assert res.status_code == 404

def test_missing_storage_evidence_file(operator_headers):
    """Requesting missing evidence file via /storage returns 404."""
    res = client.get("/storage/evidence/nonexistent_crop_9999.jpg", headers=operator_headers)
    assert res.status_code == 404

def test_missing_report_download(operator_headers):
    """Requesting download of non-existent report returns 404."""
    res = client.get(f"/api/v1/reports/download/{uuid.uuid4()}", headers=operator_headers)
    assert res.status_code == 404

def test_missing_model_checkpoint_x3d():
    """Initializing X3D with non-existent checkpoint raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        detector = object.__new__(X3DViolenceDetector)
        detector.device = torch.device("cpu")
        detector.checkpoint_path = "nonexistent_checkpoint_file.pt"
        detector._load_model()

# =========================================================================
# STEP 4: AI / Model Failure Handling
# =========================================================================

def test_x3d_inference_exception_handling(operator_headers, dummy_mp4_bytes):
    """When X3D-M inference raises an exception during /violence/analyze, error is caught."""
    up_res = client.post(
        "/api/v1/violence/upload",
        files={"file": ("test_vid.mp4", dummy_mp4_bytes, "video/mp4")},
        headers=operator_headers
    )
    assert up_res.status_code == 201
    vid_id = up_res.json()["video_id"]

    with patch("app.pipeline.x3d_violence_detector.X3DViolenceDetector.detect_violence", side_effect=RuntimeError("Simulated CUDA OOM in X3D")):
        res = client.post(
            "/api/v1/violence/analyze",
            data={"video_id": vid_id},
            headers=operator_headers
        )
        assert res.status_code == 500

def test_face_engine_missing_crop():
    """StudentIdentifier handles missing crop gracefully by returning None."""
    from app.services.student_identifier import StudentIdentifier
    identifier = StudentIdentifier()
    res = asyncio.run(identifier.identify_face_in_crop("nonexistent_crop_path_123.jpg"))
    assert res is None

def test_yolo_detector_exception_handling():
    """YOLO detector handles inference exceptions."""
    from app.pipeline.detector import YOLOv8Detector
    detector = YOLOv8Detector()
    with patch.object(detector, "model", side_effect=RuntimeError("YOLO runtime error")):
        with pytest.raises(RuntimeError):
            detector.detect_batch([np.zeros((64, 64, 3), dtype=np.uint8)])

def test_clip_embedder_failure():
    """CLIP embedder handles empty or invalid image array."""
    from app.pipeline.embedder import CLIPEmbedder
    embedder = CLIPEmbedder()
    empty_img = np.zeros((0, 0, 3), dtype=np.uint8)
    with pytest.raises(Exception):
        embedder.embed_image(empty_img)

# =========================================================================
# STEP 5: Database Failure Handling
# =========================================================================

def test_db_unique_constraint_violation():
    """Database rolls back on unique email constraint violation."""
    from sqlalchemy.exc import IntegrityError
    unique_email = f"dup_{uuid.uuid4().hex}@resilience.audit"
    async def _test_dup():
        async with SessionLocal() as db:
            u1 = User(
                id=uuid.uuid4(),
                email=unique_email,
                hashed_password="hash",
                full_name="Original User",
                role="admin",
                is_active=True
            )
            db.add(u1)
            await db.commit()

            dup_user = User(
                id=uuid.uuid4(),
                email=unique_email,  # duplicate email
                hashed_password="hash",
                full_name="Duplicate User",
                role="admin",
                is_active=True
            )
            db.add(dup_user)
            with pytest.raises(IntegrityError):
                await db.commit()
            await db.rollback()
    asyncio.run(_test_dup())

def test_db_connection_error_handling(operator_headers):
    """When DB session fails during request, API returns 500."""
    async def _failing_get_db():
        raise Exception("Simulated DB connection pool exhaustion")
        yield

    app.dependency_overrides[deps.get_db] = _failing_get_db
    try:
        res = client.get("/api/v1/cameras", headers=operator_headers)
        assert res.status_code == 500
    finally:
        app.dependency_overrides.pop(deps.get_db, None)

# =========================================================================
# STEP 6: Redis / Celery Failure Handling
# =========================================================================

def test_celery_task_permanent_error_handling():
    """Celery process_video does not retry permanent errors (e.g. FileNotFoundError)."""
    nonexistent_vid_id = uuid.uuid4()
    async def _create_bad_video():
        async with SessionLocal() as db:
            vid = Video(
                id=nonexistent_vid_id,
                title="Bad Video",
                filename="bad.mp4",
                original_filename="bad.mp4",
                file_path="nonexistent_storage_path.mp4",
                status="queued",
                uploaded_by=OPERATOR_USER_ID
            )
            db.add(vid)
            await db.commit()
    asyncio.run(_create_bad_video())

    # Execute celery task using Celery's .apply()
    try:
        process_video.apply(args=[str(nonexistent_vid_id)])
    except Exception:
        pass

    # Verify status transitioned to failed
    async def _check_status():
        async with SessionLocal() as db:
            res = await db.get(Video, nonexistent_vid_id)
            return res.status
    final_status = asyncio.run(_check_status())
    assert final_status == "failed"

def test_celery_enqueue_failure_handling(operator_headers, dummy_mp4_bytes):
    """When Celery broker is down, /videos/upload marks video as failed in DB."""
    with patch("app.tasks.video_tasks.process_video.delay", side_effect=ConnectionError("Redis broker offline")):
        res = client.post(
            "/api/v1/videos/upload",
            files={"file": ("upload_offline.mp4", dummy_mp4_bytes, "video/mp4")},
            headers=operator_headers
        )
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "failed"
        assert "Queue Failure" in data["current_stage"]

# =========================================================================
# STEP 7: Qdrant Failure Handling
# =========================================================================

def test_qdrant_connection_error_upsert():
    """QdrantVectorStore handles connection error when upserting vectors."""
    store = QdrantVectorStore()
    with patch.object(store.client, "upsert", side_effect=ConnectionError("Qdrant daemon down")):
        with pytest.raises(ConnectionError):
            store.upsert_vectors([{"id": uuid.uuid4(), "vector": [0.0]*512, "payload": {}}])

def test_qdrant_search_error_api(operator_headers):
    """When Qdrant fails during hybrid search, /search returns controlled 500."""
    with patch("app.services.vector_store.QdrantVectorStore.search_by_text", side_effect=ConnectionError("Qdrant unreachable")):
        res = client.post(
            "/api/v1/search",
            json={"query": "person walking in hallway"},
            headers=operator_headers
        )
        assert res.status_code == 500
        assert "failed to execute search query" in res.json()["detail"].lower()

# =========================================================================
# STEP 8: Duplicate / Concurrent Processing
# =========================================================================

def test_duplicate_video_upload_creates_isolated_ids(operator_headers, dummy_mp4_bytes):
    """Uploading the identical video file twice generates distinct IDs and filenames."""
    res1 = client.post(
        "/api/v1/violence/upload",
        files={"file": ("dup.mp4", dummy_mp4_bytes, "video/mp4")},
        headers=operator_headers
    )
    res2 = client.post(
        "/api/v1/violence/upload",
        files={"file": ("dup.mp4", dummy_mp4_bytes, "video/mp4")},
        headers=operator_headers
    )
    assert res1.status_code == 201
    assert res2.status_code == 201
    assert res1.json()["video_id"] != res2.json()["video_id"]
    assert res1.json()["filename"] != res2.json()["filename"]

def test_repeated_report_generation(admin_headers):
    """Repeated report generation requests for the same incident return the existing report (idempotency)."""
    inc_id = uuid.uuid4()
    async def _create_inc():
        async with SessionLocal() as db:
            inc = Incident(
                id=inc_id,
                camera_id=TEST_CAM_ID,
                incident_type="fight",
                timestamp=datetime.now(timezone.utc),
                confidence=0.9
            )
            db.add(inc)
            await db.commit()
    asyncio.run(_create_inc())

    payload = {"title": "Incident Dossier", "incident_type": "fight", "incident_id": str(inc_id), "data": {"evidence": "clips"}}
    res1 = client.post("/api/v1/reports/generate", json=payload, headers=admin_headers)
    res2 = client.post("/api/v1/reports/generate", json=payload, headers=admin_headers)
    assert res1.status_code == 201
    assert res2.status_code == 201
    assert res1.json()["id"] == res2.json()["id"]

# =========================================================================
# STEP 9: Partial Pipeline Failure
# =========================================================================

def test_pipeline_stage1_validation_failure():
    """VideoProcessingOrchestrator raises FileNotFoundError if file does not exist."""
    async def _test():
        async with SessionLocal() as db:
            from app.pipeline.orchestrator import VideoProcessingOrchestrator
            vid_id = uuid.uuid4()
            vid = Video(
                id=vid_id,
                title="Test",
                filename="t.mp4",
                original_filename="t.mp4",
                file_path="missing_file.mp4",
                uploaded_by=OPERATOR_USER_ID
            )
            db.add(vid)
            await db.commit()

            callback_mock = AsyncMock()
            orchestrator = VideoProcessingOrchestrator(db, callback_mock)
            with pytest.raises(FileNotFoundError):
                await orchestrator.execute(vid_id)
    asyncio.run(_test())

def test_pipeline_incident_engine_resilience():
    """EventDetectionEngine handles processing when video has no events."""
    from app.event_engine.event_engine import EventDetectionEngine
    async def _test():
        async with SessionLocal() as db:
            # Running with non-existent camera / video IDs completes without unhandled crash
            await EventDetectionEngine.process_video_events(db, uuid.uuid4(), uuid.uuid4())
    asyncio.run(_test())

# =========================================================================
# STEP 10: Timeout / Long-Running Video
# =========================================================================

def test_long_video_processing_simulation():
    """Simulates 100-frame video through X3D temporal window extraction."""
    temp_p = tempfile.mktemp(suffix=".mp4")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(temp_p, fourcc, 25.0, (64, 64))
    for _ in range(100):
        out.write(np.zeros((64, 64, 3), dtype=np.uint8))
    out.release()

    detector = X3DViolenceDetector()
    result = detector.detect_violence(temp_p, window_duration_sec=2.0, stride_sec=1.0)
    if os.path.exists(temp_p):
        os.remove(temp_p)

    assert result.total_frames == 100
    assert len(result.windows) >= 3
    assert result.video_duration == 4.0

def test_sliding_window_bounds():
    """Sliding window generator respects boundaries and does not exceed video frames."""
    detector = X3DViolenceDetector()
    raw_frames = [np.zeros((64, 64, 3), dtype=np.uint8) for _ in range(30)]
    clip = detector.preprocess_clip(raw_frames, 0, 30)
    assert clip.shape == (1, 3, 16, 224, 224)

# =========================================================================
# STEP 11: Frontend Error Handling Contracts
# =========================================================================

def test_frontend_error_mapping_401():
    """Unauthenticated request returns 401."""
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401

def test_frontend_error_mapping_403(operator_headers):
    """Operator attempting admin action returns 403."""
    res = client.delete(f"/api/v1/cameras/{uuid.uuid4()}", headers=operator_headers)
    assert res.status_code == 403

def test_frontend_error_mapping_404(operator_headers):
    """Missing resource returns 404."""
    res = client.get(f"/api/v1/videos/{uuid.uuid4()}", headers=operator_headers)
    assert res.status_code == 404

def test_frontend_error_mapping_422(operator_headers):
    """Invalid JSON payload returns 422 with unprocessable entity details."""
    res = client.post("/api/v1/search", json={"query": None}, headers=operator_headers)
    assert res.status_code == 422

# =========================================================================
# STEP 12: Resource Cleanup
# =========================================================================

def test_cleanup_temp_file_on_upload_rejection(operator_headers):
    """Rejected upload (e.g. 0-byte or corrupted) cleans up saved file from disk."""
    initial_files = set(os.listdir(settings.STORAGE_DIR))
    res = client.post(
        "/api/v1/violence/upload",
        files={"file": ("zero.mp4", b"", "video/mp4")},
        headers=operator_headers
    )
    assert res.status_code == 400
    after_files = set(os.listdir(settings.STORAGE_DIR))
    assert after_files == initial_files

def test_videocapture_release_on_error():
    """Corrupted file inspection safely closes VideoCapture handle."""
    temp_p = tempfile.mktemp(suffix=".mp4")
    with open(temp_p, "wb") as f:
        f.write(b"CORRUPTED_STREAM")
    is_valid, msg = check_video_integrity(temp_p)
    assert is_valid is False
    os.remove(temp_p)
    assert not os.path.exists(temp_p)

def test_vector_store_clean_reprocessing():
    """Vector store delete_vectors_by_video_id executes without crashing."""
    store = QdrantVectorStore()
    test_vid = uuid.uuid4()
    store.delete_vectors_by_video_id(test_vid)
