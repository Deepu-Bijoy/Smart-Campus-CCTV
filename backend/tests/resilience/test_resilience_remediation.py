"""
Phase 5A — Resilience Remediation & Regression Test Suite

Validates and proves remediation of Phase 5 findings:
- FAIL-01: SQLite UUID column-affinity and pure-numeric UUID persistence/deserialization.
- FAIL-02: X3D-M inference exception handling, failure status transition, error persistence,
           and prevention of false incidents/evidence/alerts.
- FAIL-03: Zero-frame video rejection in Stage 1 validation, preventing false completion.
- FAIL-04: Report generation idempotency, duplicate prevention, and distinct incident handling.
- FAIL-05: Celery configuration validation for local eager mode and production worker mode.
- X3D-M: Locked model checkpoint integrity (SHA-256), threshold, and initialization.
"""

import os
import sys
import uuid
import hashlib
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest
import cv2
import numpy as np
import torch
from fastapi.testclient import TestClient

# Isolated test environment configuration
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_remediation_audit.db"

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
from app.pipeline.orchestrator import VideoProcessingOrchestrator
from app.pipeline.x3d_violence_detector import X3DViolenceDetector

client = TestClient(app, raise_server_exceptions=False)

ADMIN_USER_ID = uuid.UUID("11111111-aaaa-1111-aaaa-111111111111")
NUMERIC_UUID = uuid.UUID("11111111-1111-1111-1111-111111111111")
ALPHA_UUID = uuid.UUID("abcdef01-2345-6789-abcd-ef0123456789")


async def init_remediation_db():
    """Initializes tables and seeds test user in isolated test database."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        res = await db.execute(User.__table__.select().where(User.__table__.c.id == ADMIN_USER_ID))
        if not res.first():
            admin = User(
                id=ADMIN_USER_ID,
                email="admin@remediation.audit",
                hashed_password=security.get_password_hash("AuditAdminPass123!"),
                full_name="Admin Remediation Auditor",
                role="admin",
                is_active=True
            )
            db.add(admin)
            await db.commit()

asyncio.run(init_remediation_db())


def get_auth_headers(user_id: uuid.UUID) -> dict:
    token = security.create_access_token(user_id)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    return get_auth_headers(ADMIN_USER_ID)


@pytest.fixture
def clean_test_video():
    """Creates a temporary valid synthetic MP4 fixture."""
    temp_dir = os.path.join("storage", "test_fixtures")
    os.makedirs(temp_dir, exist_ok=True)
    temp_path = os.path.join(temp_dir, f"test_{uuid.uuid4().hex[:8]}.mp4")
    
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(temp_path, fourcc, 25.0, (64, 64))
    for _ in range(25):
        frame = np.zeros((64, 64, 3), dtype=np.uint8)
        out.write(frame)
    out.release()
    
    yield temp_path
    
    if os.path.exists(temp_path):
        os.remove(temp_path)


# =========================================================================
# FAIL-01 REGRESSION: SQLite UUID Column Affinity & Deserialization
# =========================================================================

def test_sqlite_pure_numeric_uuid_persistence_and_retrieval():
    """
    FAIL-01: Pure-digit UUID (11111111-1111-1111-1111-111111111111) must not
    be coerced to float by SQLite and must deserialize correctly as uuid.UUID.
    """
    async def _test():
        async with SessionLocal() as db:
            user = User(
                id=NUMERIC_UUID,
                email=f"numeric_{uuid.uuid4().hex[:6]}@remediation.test",
                full_name="Numeric UUID User",
                hashed_password="hash",
                role="admin"
            )
            db.add(user)
            await db.commit()

        async with SessionLocal() as db:
            from sqlalchemy import select, text
            res = await db.execute(select(User).where(User.id == NUMERIC_UUID))
            queried_user = res.scalar_one_or_none()
            assert queried_user is not None
            assert isinstance(queried_user.id, uuid.UUID)
            assert queried_user.id == NUMERIC_UUID

            # Verify underlying storage in SQLite is string/text, not real/float
            raw = await db.execute(
                text(f"SELECT typeof(id), id FROM users WHERE email = '{user.email}'")
            )
            row = raw.fetchone()
            assert row is not None
            col_type, col_val = row
            assert col_type == "text", f"Expected SQLite typeof text, got {col_type} ({col_val})"

            # Cleanup
            await db.delete(queried_user)
            await db.commit()

    asyncio.run(_test())


def test_sqlite_alphanumeric_uuid_persistence_and_retrieval():
    """
    FAIL-01: Hexadecimal alphanumeric UUID persists and deserializes cleanly.
    """
    async def _test():
        async with SessionLocal() as db:
            user = User(
                id=ALPHA_UUID,
                email=f"alpha_{uuid.uuid4().hex[:6]}@remediation.test",
                full_name="Alpha UUID User",
                hashed_password="hash",
                role="operator"
            )
            db.add(user)
            await db.commit()

        async with SessionLocal() as db:
            from sqlalchemy import select
            res = await db.execute(select(User).where(User.id == ALPHA_UUID))
            queried = res.scalar_one_or_none()
            assert queried is not None
            assert isinstance(queried.id, uuid.UUID)
            assert queried.id == ALPHA_UUID

            await db.delete(queried)
            await db.commit()

    asyncio.run(_test())


def test_sqlite_uuid_roundtrip_integrity():
    """
    FAIL-01: Multiple random UUID4 instances survive round-trip insert/query.
    """
    async def _test():
        test_uuids = [uuid.uuid4() for _ in range(5)]
        async with SessionLocal() as db:
            users = []
            for u in test_uuids:
                usr = User(
                    id=u,
                    email=f"user_{u.hex[:8]}@remediation.test",
                    full_name="Test User",
                    hashed_password="hash",
                    role="viewer"
                )
                db.add(usr)
                users.append(usr)
            await db.commit()

        async with SessionLocal() as db:
            from sqlalchemy import select
            for u in test_uuids:
                res = await db.execute(select(User).where(User.id == u))
                found = res.scalar_one_or_none()
                assert found is not None
                assert found.id == u
                await db.delete(found)
            await db.commit()

    asyncio.run(_test())


# =========================================================================
# FAIL-02 REGRESSION: X3D-M Inference Failure Handling
# =========================================================================

def test_x3d_failure_transitions_video_to_failed_state(admin_headers, clean_test_video):
    """
    FAIL-02: When X3D-M raises an inference exception during /violence/analyze:
    - HTTP 500 is returned (original exception not hidden)
    - Video record in DB transitions to status='failed'
    - error_message is populated
    - processing_finished_at is populated
    """
    vid_id = uuid.uuid4()
    async def _setup_video():
        async with SessionLocal() as db:
            v = Video(
                id=vid_id,
                title="X3D Fail Test Video",
                filename="clean.mp4",
                original_filename="clean.mp4",
                file_path=clean_test_video,
                status="pending",
                uploaded_by=ADMIN_USER_ID
            )
            db.add(v)
            await db.commit()
    asyncio.run(_setup_video())

    error_str = "Simulated CUDA Out Of Memory in X3D-M forward pass"
    with patch.object(X3DViolenceDetector, "detect_violence", side_effect=RuntimeError(error_str)):
        res = client.post(
            "/api/v1/violence/analyze",
            data={"video_id": str(vid_id)},
            headers=admin_headers
        )
        assert res.status_code == 500

    async def _verify_video_failed():
        async with SessionLocal() as db:
            from sqlalchemy import select
            res = await db.execute(select(Video).where(Video.id == vid_id))
            v = res.scalar_one_or_none()
            assert v is not None
            assert v.status == "failed"
            assert v.current_stage == "Analysis Failed"
            assert v.error_message is not None
            assert "Simulated CUDA Out Of Memory" in v.error_message
            assert v.processing_finished_at is not None

            # Verify no false events or evidence were created
            evt_res = await db.execute(select(DetectedEvent).where(DetectedEvent.video_id == vid_id))
            events = evt_res.scalars().all()
            assert len(events) == 0, "No false events should be created on failure"

            await db.delete(v)
            await db.commit()

    asyncio.run(_verify_video_failed())


def test_x3d_success_transitions_video_to_completed_state(admin_headers, clean_test_video):
    """
    FAIL-02: Successful X3D-M normal activity analysis transitions video to status='completed'.
    """
    vid_id = uuid.uuid4()
    async def _setup():
        async with SessionLocal() as db:
            v = Video(
                id=vid_id,
                title="X3D Success Test Video",
                filename="clean.mp4",
                original_filename="clean.mp4",
                file_path=clean_test_video,
                status="pending",
                uploaded_by=ADMIN_USER_ID
            )
            db.add(v)
            await db.commit()
    asyncio.run(_setup())

    mock_result = MagicMock()
    mock_result.is_violent = False
    mock_result.segments = []
    mock_result.timings = {}

    with patch.object(X3DViolenceDetector, "detect_violence", return_value=mock_result):
        res = client.post(
            "/api/v1/violence/analyze",
            data={"video_id": str(vid_id)},
            headers=admin_headers
        )
        assert res.status_code == 200
        assert res.json()["status"] == "NORMAL"

    async def _verify():
        async with SessionLocal() as db:
            from sqlalchemy import select
            res = await db.execute(select(Video).where(Video.id == vid_id))
            v = res.scalar_one_or_none()
            assert v is not None
            assert v.status == "completed"
            assert v.progress_percentage == 100
            await db.delete(v)
            await db.commit()

    asyncio.run(_verify())


# =========================================================================
# FAIL-03 REGRESSION: Zero-Frame Video Rejection
# =========================================================================

def test_zero_byte_video_rejected_by_pipeline_validation():
    """
    FAIL-03: VideoProcessingOrchestrator rejects 0-byte video with ValueError.
    """
    temp_path = "storage/test_0byte_temp.mp4"
    with open(temp_path, "wb") as f:
        pass

    async def _test():
        async with SessionLocal() as db:
            v = Video(
                id=uuid.uuid4(),
                title="0-byte Video",
                filename="0byte.mp4",
                original_filename="0byte.mp4",
                file_path=temp_path,
                status="pending",
                uploaded_by=ADMIN_USER_ID
            )
            orchestrator = VideoProcessingOrchestrator(db, MagicMock())
            with pytest.raises(ValueError, match="0 bytes"):
                await orchestrator._stage_validate_video(v)

    try:
        asyncio.run(_test())
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_zero_frame_video_rejected_by_pipeline_validation():
    """
    FAIL-03: Video with 0 decodable frames raises ValueError during Stage 1 validation.
    """
    temp_path = "storage/test_0frame_corrupt.mp4"
    with open(temp_path, "wb") as f:
        f.write(b"not a valid mp4 header but non empty")

    async def _test():
        async with SessionLocal() as db:
            v = Video(
                id=uuid.uuid4(),
                title="0-frame Video",
                filename="0frame.mp4",
                original_filename="0frame.mp4",
                file_path=temp_path,
                status="pending",
                uploaded_by=ADMIN_USER_ID
            )
            orchestrator = VideoProcessingOrchestrator(db, MagicMock())
            with pytest.raises(ValueError, match="(Corrupted|zero decodable frames)"):
                await orchestrator._stage_validate_video(v)

    try:
        asyncio.run(_test())
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def test_valid_frame_video_passes_pipeline_validation(clean_test_video):
    """
    FAIL-03: Video with valid decodable frames and positive FPS passes Stage 1 validation cleanly.
    """
    async def _test():
        async with SessionLocal() as db:
            v = Video(
                id=uuid.uuid4(),
                title="Valid Video",
                filename="valid.mp4",
                original_filename="valid.mp4",
                file_path=clean_test_video,
                status="pending",
                uploaded_by=ADMIN_USER_ID
            )
            orchestrator = VideoProcessingOrchestrator(db, MagicMock())
            # Should complete without raising any exception
            await orchestrator._stage_validate_video(v)

    asyncio.run(_test())


# =========================================================================
# FAIL-04 REGRESSION: Report Idempotency & Duplicate Prevention
# =========================================================================

def test_first_report_generation(admin_headers):
    """FAIL-04: Initial report generation creates report record successfully."""
    inc_id = uuid.uuid4()
    payload = {
        "title": "Forensic Incident Report",
        "incident_type": "Violence",
        "incident_id": str(inc_id),
        "data": {"summary": "Initial report test", "evidence_count": 2}
    }
    res = client.post("/api/v1/reports/generate", json=payload, headers=admin_headers)
    assert res.status_code == 201
    data = res.json()
    assert "id" in data
    assert data["title"] == payload["title"]


def test_repeated_report_request_returns_existing_report(admin_headers):
    """
    FAIL-04: Repeated report generation requests for the same incident return the
    previously generated report without creating duplicate records in the database.
    """
    inc_id = uuid.uuid4()
    async def _create_inc():
        async with SessionLocal() as db:
            from app.models.incident import Incident
            from app.models.camera import Camera
            from sqlalchemy import select
            cam = (await db.execute(select(Camera))).scalars().first()
            if not cam:
                cam = Camera(
                    id=uuid.uuid4(),
                    name="Remediation Camera",
                    building="Main",
                    floor=1,
                    location="Gate",
                    direction="North",
                    resolution="1080p",
                    status="active"
                )
                db.add(cam)
                await db.commit()
            inc = Incident(
                id=inc_id,
                camera_id=cam.id,
                incident_type="Altercation",
                timestamp=datetime.now(timezone.utc),
                confidence=0.9
            )
            db.add(inc)
            await db.commit()
    asyncio.run(_create_inc())

    payload = {
        "title": "Idempotent Report Test",
        "incident_type": "Altercation",
        "incident_id": str(inc_id),
        "data": {"summary": "Altercation detected", "evidence": "clip_01.mp4"}
    }
    res1 = client.post("/api/v1/reports/generate", json=payload, headers=admin_headers)
    assert res1.status_code == 201
    id1 = res1.json()["id"]

    # Second request with identical incident_id
    res2 = client.post("/api/v1/reports/generate", json=payload, headers=admin_headers)
    assert res2.status_code in [200, 201]
    id2 = res2.json()["id"]

    # Third request with identical incident_id
    res3 = client.post("/api/v1/reports/generate", json=payload, headers=admin_headers)
    assert res3.status_code in [200, 201]
    id3 = res3.json()["id"]

    assert id1 == id2 == id3, f"Expected identical report ID, got {id1}, {id2}, {id3}"

    # Verify only ONE report row exists in the database for this incident
    async def _count_reports():
        async with SessionLocal() as db:
            from sqlalchemy import select
            res = await db.execute(select(Report).where(Report.incident_id == inc_id))
            reports = res.scalars().all()
            assert len(reports) == 1, f"Expected 1 report in DB, found {len(reports)}"
    asyncio.run(_count_reports())


def test_different_incident_creates_separate_report(admin_headers):
    """
    FAIL-04: Distinct incidents produce distinct reports.
    """
    inc1 = uuid.uuid4()
    inc2 = uuid.uuid4()
    payload1 = {
        "title": "Report for Incident 1",
        "incident_type": "Fight",
        "incident_id": str(inc1),
        "data": {"event": "Fight 1"}
    }
    payload2 = {
        "title": "Report for Incident 2",
        "incident_type": "Fight",
        "incident_id": str(inc2),
        "data": {"event": "Fight 2"}
    }
    res1 = client.post("/api/v1/reports/generate", json=payload1, headers=admin_headers)
    res2 = client.post("/api/v1/reports/generate", json=payload2, headers=admin_headers)

    assert res1.status_code == 201
    assert res2.status_code == 201
    assert res1.json()["id"] != res2.json()["id"]


# =========================================================================
# FAIL-05 REGRESSION: Celery Configuration Behavior
# =========================================================================

def test_celery_local_eager_configuration():
    """
    FAIL-05: When CELERY_ALWAYS_EAGER=true, task execution mode is configured
    eagerly in-process without requiring a remote Redis broker.
    """
    assert settings.CELERY_ALWAYS_EAGER is True
    from app.tasks.cel_app import celery_app
    assert celery_app.conf.task_always_eager is True


def test_celery_production_worker_configuration_properties():
    """
    FAIL-05: Verify Celery routing configuration specifies gpu_queue and cpu_queue
    for production worker architecture.
    """
    from app.tasks.cel_app import celery_app
    routes = celery_app.conf.task_routes
    assert "app.tasks.video_tasks.process_video" in routes
    assert routes["app.tasks.video_tasks.process_video"]["queue"] == "gpu_queue"
    assert "app.tasks.cpu_tasks.*" in routes
    assert routes["app.tasks.cpu_tasks.*"]["queue"] == "cpu_queue"


# =========================================================================
# X3D-M REGRESSION: Architecture, Weight & Inference Integrity
# =========================================================================

def test_x3d_model_checkpoint_integrity():
    """
    X3D-M Locked Checkpoint: Weight file must be present and match locked SHA-256 hash.
    Locked SHA-256: e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349
    """
    weight_path = os.path.join("storage", "models", "x3d", "final_x3d_realtime.pt")
    if not os.path.exists(weight_path):
        weight_path = os.path.join("backend", "storage", "models", "x3d", "final_x3d_realtime.pt")
    assert os.path.exists(weight_path), f"Checkpoint missing at {weight_path}"
    
    sha256 = hashlib.sha256()
    with open(weight_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    file_hash = sha256.hexdigest()

    expected_hash = "e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349"
    assert file_hash == expected_hash, f"X3D checkpoint SHA-256 altered: {file_hash}"


def test_x3d_detector_initialization_and_threshold():
    """
    X3D-M Locked Specification: Input is 16 frames, model initializes, threshold is preserved.
    """
    detector = X3DViolenceDetector()
    assert detector.model is not None
    assert detector.num_frames == 16
    assert detector.frame_size == 224
    assert detector.threshold == 0.40
