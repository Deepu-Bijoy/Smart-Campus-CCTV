import os
import sys
import uuid
import io
import zipfile
import asyncio
import time
from datetime import datetime, timezone, timedelta
import pytest
import jwt
from fastapi.testclient import TestClient

# Configure isolated test environment
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_security_audit.db"

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.main import app
from app.core import security
from app.core.config import settings
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.models.user import User
from app.models.camera import Camera, VirtualZone
from app.models.video import Video
from app.models.incident import Incident, Evidence, DetectedEvent
from app.models.report import Report
from app.models.student import Student

client = TestClient(app)

USER_A_ID = uuid.UUID("11111111-aaaa-1111-aaaa-111111111111")
USER_B_ID = uuid.UUID("22222222-bbbb-2222-bbbb-222222222222")
ADMIN_ID = uuid.UUID("33333333-cccc-3333-cccc-333333333333")
INACTIVE_ID = uuid.UUID("44444444-dddd-4444-dddd-444444444444")
GLOBAL_CAM_ID = uuid.UUID("55555555-eeee-5555-eeee-555555555555")

PASSWORD_PLAIN = "SecretPassword123!"

async def setup_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
        
    async with SessionLocal() as db:
        hashed = security.get_password_hash(PASSWORD_PLAIN)
        user_a = User(
            id=USER_A_ID,
            email="operator_a@campus.edu",
            hashed_password=hashed,
            full_name="Operator Alice",
            is_active=True,
            role="operator"
        )
        user_b = User(
            id=USER_B_ID,
            email="operator_b@campus.edu",
            hashed_password=hashed,
            full_name="Operator Bob",
            is_active=True,
            role="operator"
        )
        user_admin = User(
            id=ADMIN_ID,
            email="admin@campus.edu",
            hashed_password=hashed,
            full_name="Admin Security Officer",
            is_active=True,
            role="admin"
        )
        user_inactive = User(
            id=INACTIVE_ID,
            email="inactive@campus.edu",
            hashed_password=hashed,
            full_name="Inactive Employee",
            is_active=False,
            role="operator"
        )
        cam = Camera(
            id=GLOBAL_CAM_ID,
            name="Main Gate Cam 01",
            building="Gate House",
            floor=1,
            location="Main Entrance",
            direction="South",
            resolution="1080p",
            status="active"
        )
        db.add_all([user_a, user_b, user_admin, user_inactive, cam])
        await db.commit()

def run_async(coro):
    return asyncio.run(coro)

run_async(setup_test_db())

def get_token_for(user_id: uuid.UUID, expires_delta: timedelta = None) -> str:
    return security.create_access_token(user_id, expires_delta=expires_delta)

def auth_headers(user_id: uuid.UUID) -> dict:
    tok = get_token_for(user_id)
    return {"Authorization": f"Bearer {tok}"}

def test_auth_login_valid_credentials():
    resp = client.post("/api/v1/auth/login", data={"username": "operator_a@campus.edu", "password": PASSWORD_PLAIN})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"].lower() == "bearer"

def test_auth_login_invalid_password():
    resp = client.post("/api/v1/auth/login", data={"username": "operator_a@campus.edu", "password": "WrongPassword!"})
    assert resp.status_code == 400
    assert "Incorrect email or password" in resp.json()["detail"]

def test_auth_login_nonexistent_user():
    resp = client.post("/api/v1/auth/login", data={"username": "ghost@campus.edu", "password": PASSWORD_PLAIN})
    assert resp.status_code == 400
    assert "Incorrect email or password" in resp.json()["detail"]

def test_auth_login_inactive_user():
    resp = client.post("/api/v1/auth/login", data={"username": "inactive@campus.edu", "password": PASSWORD_PLAIN})
    assert resp.status_code == 400
    assert "Inactive user" in resp.json()["detail"]

def test_auth_missing_token_rejected():
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401

def test_auth_invalid_signature_rejected():
    forged_token = jwt.encode({"sub": str(USER_A_ID), "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "WRONG_SECRET_KEY", algorithm="HS256")
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert resp.status_code == 401

def test_auth_expired_token_rejected():
    expired_token = get_token_for(USER_A_ID, expires_delta=timedelta(minutes=-10))
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired_token}"})
    assert resp.status_code == 401

def test_auth_malformed_token_rejected():
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not.a.valid.jwt.payload"})
    assert resp.status_code == 401

def test_auth_deleted_or_nonexistent_user_token_rejected():
    random_user_id = uuid.uuid4()
    ghost_token = get_token_for(random_user_id)
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {ghost_token}"})
    assert resp.status_code == 401

def test_auth_inactive_user_token_rejected():
    inactive_token = get_token_for(INACTIVE_ID)
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {inactive_token}"})
    assert resp.status_code == 403
    assert "Inactive user" in resp.json()["detail"]

def test_auth_logout_and_revocation():
    token = get_token_for(USER_A_ID)
    headers = {"Authorization": f"Bearer {token}"}
    resp = client.post("/api/v1/auth/logout", headers=headers)
    assert resp.status_code == 200
    assert "revoked" in resp.json()["message"].lower()
    resp_subsequent = client.get("/api/v1/auth/me", headers=headers)
    assert resp_subsequent.status_code == 401

def test_rbac_unauthenticated_requests_blocked():
    protected_paths = [
        ("GET", "/api/v1/cameras"),
        ("POST", "/api/v1/cameras"),
        ("GET", "/api/v1/students"),
        ("GET", "/api/v1/reports"),
        ("GET", "/api/v1/videos"),
        ("GET", "/api/v1/events"),
        ("GET", "/api/v1/violence/history"),
    ]
    for method, path in protected_paths:
        if method == "GET":
            r = client.get(path)
        else:
            r = client.post(path, json={})
        assert r.status_code == 401

def test_rbac_operator_cannot_delete_camera():
    cam_id = uuid.uuid4()
    async def create_cam():
        async with SessionLocal() as db:
            db.add(Camera(
                id=cam_id,
                name=f"Cam {cam_id.hex[:6]}",
                building="Admin Block",
                floor=1,
                location="Quad",
                direction="North",
                resolution="1080p",
                status="active"
            ))
            await db.commit()
    run_async(create_cam())
    resp = client.delete(f"/api/v1/cameras/{cam_id}", headers=auth_headers(USER_A_ID))
    assert resp.status_code == 403

def test_rbac_operator_cannot_delete_evidence():
    ev_id = uuid.uuid4()
    inc_id = uuid.uuid4()
    async def create_evidence():
        async with SessionLocal() as db:
            db.add(Incident(
                id=inc_id,
                incident_type="Fight",
                camera_id=GLOBAL_CAM_ID,
                confidence=0.9
            ))
            db.add(Evidence(
                id=ev_id,
                incident_id=inc_id,
                evidence_type="screenshot",
                file_path="storage/dummy.jpg"
            ))
            await db.commit()
    run_async(create_evidence())

    resp = client.delete(f"/api/v1/evidence/{ev_id}", headers=auth_headers(USER_B_ID))
    assert resp.status_code == 403

def test_idor_videos_endpoint_is_properly_isolated():
    vid_a = uuid.uuid4()
    async def setup_video():
        async with SessionLocal() as db:
            db.add(Video(
                id=vid_a,
                title="Alice Secret CCTV",
                filename="a.mp4",
                original_filename="a.mp4",
                file_path="storage/a.mp4",
                uploaded_by=USER_A_ID,
                status="completed"
            ))
            await db.commit()
    run_async(setup_video())

    resp_b = client.get(f"/api/v1/videos/{vid_a}", headers=auth_headers(USER_B_ID))
    assert resp_b.status_code == 404

    del_b = client.delete(f"/api/v1/videos/{vid_a}", headers=auth_headers(USER_B_ID))
    assert del_b.status_code == 404

def test_idor_violence_result_blocked_for_cross_user():
    vid_a = uuid.uuid4()
    inc_a = uuid.uuid4()
    async def setup_violence_data():
        async with SessionLocal() as db:
            db.add(Video(
                id=vid_a,
                title="Alice Secret Violence Video",
                filename="a_v.mp4",
                original_filename="a_v.mp4",
                file_path="storage/a_v.mp4",
                uploaded_by=USER_A_ID,
                status="completed"
            ))
            db.add(Incident(
                id=inc_a,
                incident_type="Violence",
                camera_id=GLOBAL_CAM_ID,
                confidence=0.88,
                explanation="altercation from 1.0s to 5.0s"
            ))
            db.add(DetectedEvent(
                id=uuid.uuid4(),
                video_id=vid_a,
                camera_id=GLOBAL_CAM_ID,
                incident_id=inc_a,
                event_type="VIOLENCE",
                confidence=0.88
            ))
            await db.commit()
    run_async(setup_violence_data())

    resp_b = client.get(f"/api/v1/violence/result/{vid_a}", headers=auth_headers(USER_B_ID))
    assert resp_b.status_code == 404

def test_idor_reports_blocked_for_cross_user():
    rep_id = uuid.uuid4()
    async def setup_report():
        async with SessionLocal() as db:
            db.add(Report(
                id=rep_id,
                title="Alice Confidential Incident Report",
                incident_type="Violence",
                data={"summary": "Classified", "created_by": str(USER_A_ID)}
            ))
            await db.commit()
    run_async(setup_report())

    resp_b = client.get(f"/api/v1/reports/{rep_id}", headers=auth_headers(USER_B_ID))
    assert resp_b.status_code == 404

def test_input_malformed_uuid_returns_422():
    resp = client.get("/api/v1/cameras/not-a-valid-uuid", headers=auth_headers(USER_A_ID))
    assert resp.status_code == 422

def test_input_malformed_json_body_returns_422():
    resp = client.post(
        "/api/v1/reports/generate",
        data="INVALID_JSON{{[",
        headers={"Content-Type": "application/json", **auth_headers(USER_A_ID)}
    )
    assert resp.status_code == 422

def test_input_missing_required_fields_returns_422():
    resp = client.post("/api/v1/cameras", json={"location": "Library"}, headers=auth_headers(ADMIN_ID))
    assert resp.status_code == 422

def test_upload_executable_extension_rejected():
    files = {"file": ("malicious.exe", b"MZ\x90\x00executable_bytes", "application/octet-stream")}
    resp = client.post("/api/v1/videos/upload", files=files, headers=auth_headers(USER_A_ID))
    assert resp.status_code == 400
    assert "Unsupported video format" in resp.json()["detail"]

def test_upload_empty_video_rejected():
    files = {"file": ("empty.mp4", b"", "video/mp4")}
    resp = client.post("/api/v1/violence/upload", files=files, headers=auth_headers(USER_A_ID))
    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()

def test_upload_path_traversal_filename_sanitized():
    traversal_name = "../../etc/shadow.mp4"
    files = {"file": (traversal_name, b"valid_simulated_bytes", "video/mp4")}
    resp = client.post("/api/v1/videos/upload", files=files, headers=auth_headers(USER_A_ID))
    assert not os.path.exists("../../etc/shadow.mp4")

def test_static_storage_protected_from_unauthenticated_access():
    resp = client.get("/storage/some_video.mp4")
    assert resp.status_code == 401

def test_static_storage_database_access_forbidden():
    resp = client.get("/storage/test_security_audit.db", headers=auth_headers(ADMIN_ID))
    assert resp.status_code == 403

def test_api_password_hash_not_exposed_in_me():
    resp = client.get("/api/v1/auth/me", headers=auth_headers(USER_A_ID))
    assert resp.status_code == 200
    data = resp.json()
    assert "hashed_password" not in data
    assert "password" not in data

def test_api_cors_configuration():
    assert "http://localhost:5173" in settings.BACKEND_CORS_ORIGINS
    assert "*" not in settings.BACKEND_CORS_ORIGINS

def test_db_sql_injection_resilient_via_orm():
    sqli_payload = "' OR 1=1; DROP TABLE users; --"
    resp = client.get(f"/api/v1/students?query={sqli_payload}", headers=auth_headers(USER_A_ID))
    assert resp.status_code == 200
    check_user = client.get("/api/v1/auth/me", headers=auth_headers(USER_A_ID))
    assert check_user.status_code == 200

def test_secrets_default_secret_key_neutralized():
    forged_token = jwt.encode(
        {"sub": str(ADMIN_ID), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "SUPER_SECRET_REPLACE_THIS_IN_PRODUCTION",
        algorithm="HS256"
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert resp.status_code == 401

def test_secrets_token_lifetime_hardened():
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES <= 60

def test_ws_missing_token_rejected():
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/notifications/ws"):
            pass

def test_ws_invalid_token_rejected():
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/notifications/ws?token=invalid.jwt.token"):
            pass

def test_ws_expired_token_rejected():
    expired_token = get_token_for(USER_A_ID, expires_delta=timedelta(minutes=-10))
    with pytest.raises(Exception):
        with client.websocket_connect(f"/api/v1/notifications/ws?token={expired_token}"):
            pass

def test_ws_valid_token_authenticated():
    valid_token = get_token_for(USER_A_ID)
    with client.websocket_connect(f"/api/v1/notifications/ws?token={valid_token}") as ws:
        ws.send_text("PING")
        reply = ws.receive_text()
        assert reply == "PONG"
