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

backend_path = os.path.abspath("backend")
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

# =========================================================================
# DOMAIN 1: AUTHENTICATION
# =========================================================================

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

# =========================================================================
# DOMAIN 2: SEC-01 STORAGE PROTECTION
# =========================================================================

def test_storage_unauthenticated_request_rejected():
    resp = client.get("/storage/some_video.mp4")
    assert resp.status_code == 401, f"Expected 401 got {resp.status_code}"

def test_storage_database_file_strictly_forbidden():
    resp = client.get("/storage/test_security_audit.db", headers=auth_headers(ADMIN_ID))
    assert resp.status_code == 403, f"Expected 403 Forbidden for DB file, got {resp.status_code}"

def test_storage_model_weights_strictly_forbidden():
    resp = client.get("/storage/models/x3d/final_x3d_realtime.pt", headers=auth_headers(ADMIN_ID))
    assert resp.status_code == 403, f"Expected 403 Forbidden for model weight, got {resp.status_code}"

def test_storage_authenticated_valid_media_served():
    test_media_dir = os.path.join(settings.STORAGE_DIR, "evidence")
    os.makedirs(test_media_dir, exist_ok=True)
    test_media_file = os.path.join(test_media_dir, "test_evidence_crop.jpg")
    with open(test_media_file, "wb") as f:
        f.write(b"\xFF\xD8\xFF\xE0JPEG_SAMPLE_TEST")
    
    resp = client.get("/storage/evidence/test_evidence_crop.jpg", headers=auth_headers(USER_A_ID))
    assert resp.status_code == 200, f"Expected 200 got {resp.status_code}"

# =========================================================================
# DOMAIN 3: SEC-02 DEFAULT JWT SECRET HARDENING
# =========================================================================

def test_jwt_cannot_be_forged_with_legacy_default_secret():
    # Attempt forgery using the legacy default secret key
    forged_token = jwt.encode(
        {"sub": str(ADMIN_ID), "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "SUPER_SECRET_REPLACE_THIS_IN_PRODUCTION",
        algorithm="HS256"
    )
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {forged_token}"})
    assert resp.status_code == 401, "Tokens forged with the old default secret must be rejected"

def test_active_secret_key_is_cryptographically_strong():
    assert settings.SECRET_KEY != "SUPER_SECRET_REPLACE_THIS_IN_PRODUCTION"
    assert len(settings.SECRET_KEY) >= 32

# =========================================================================
# DOMAIN 4: SEC-03 REST RBAC ENFORCEMENT
# =========================================================================

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
    assert resp.status_code == 403, f"Expected 403 Forbidden for operator, got {resp.status_code}"

def test_rbac_admin_can_delete_camera():
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

    resp = client.delete(f"/api/v1/cameras/{cam_id}", headers=auth_headers(ADMIN_ID))
    assert resp.status_code == 200, f"Expected 200 OK for admin, got {resp.status_code}"

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
    assert resp.status_code == 403, f"Expected 403 Forbidden for operator, got {resp.status_code}"

def test_rbac_admin_can_delete_evidence():
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

    resp = client.delete(f"/api/v1/evidence/{ev_id}", headers=auth_headers(ADMIN_ID))
    assert resp.status_code == 204, f"Expected 204 No Content for admin, got {resp.status_code}"

def test_rbac_operator_cannot_create_camera():
    payload = {
        "name": f"Hacked Cam {uuid.uuid4().hex[:6]}",
        "building": "Science Block",
        "floor": 2,
        "location": "Lab Hall",
        "direction": "East",
        "resolution": "4K"
    }
    resp = client.post("/api/v1/cameras", json=payload, headers=auth_headers(USER_A_ID))
    assert resp.status_code == 403

def test_rbac_admin_can_create_camera():
    payload = {
        "name": f"Admin Cam {uuid.uuid4().hex[:6]}",
        "building": "Admin Block",
        "floor": 1,
        "location": "Board Room",
        "direction": "West",
        "resolution": "1080p"
    }
    resp = client.post("/api/v1/cameras", json=payload, headers=auth_headers(ADMIN_ID))
    assert resp.status_code == 201

# =========================================================================
# DOMAIN 5: SEC-04 IDOR PREVENTION
# =========================================================================

def test_idor_videos_endpoint_is_properly_isolated():
    vid_a = uuid.uuid4()
    async def setup_video():
        async with SessionLocal() as db:
            db.add(Video(
                id=vid_a,
                title="Alice CCTV",
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

    # User B (operator) attempts to view User A's violence dossier
    resp_b = client.get(f"/api/v1/violence/result/{vid_a}", headers=auth_headers(USER_B_ID))
    assert resp_b.status_code == 404, f"IDOR fix: Expected 404 for cross-user, got {resp_b.status_code}"

def test_idor_violence_result_allowed_for_owner():
    vid_a = uuid.uuid4()
    inc_a = uuid.uuid4()
    async def setup_violence_data():
        async with SessionLocal() as db:
            db.add(Video(
                id=vid_a,
                title="Alice Own Video",
                filename="a_own.mp4",
                original_filename="a_own.mp4",
                file_path="storage/a_own.mp4",
                uploaded_by=USER_A_ID,
                status="completed"
            ))
            db.add(Incident(
                id=inc_a,
                incident_type="Violence",
                camera_id=GLOBAL_CAM_ID,
                confidence=0.85,
                explanation="altercation from 1.0s to 4.0s"
            ))
            db.add(DetectedEvent(
                id=uuid.uuid4(),
                video_id=vid_a,
                camera_id=GLOBAL_CAM_ID,
                incident_id=inc_a,
                event_type="VIOLENCE",
                confidence=0.85
            ))
            await db.commit()
    run_async(setup_violence_data())

    resp_a = client.get(f"/api/v1/violence/result/{vid_a}", headers=auth_headers(USER_A_ID))
    assert resp_a.status_code == 200
    assert resp_a.json()["video_id"] == str(vid_a)

def test_idor_violence_result_allowed_for_admin():
    vid_a = uuid.uuid4()
    async def setup_violence_data():
        async with SessionLocal() as db:
            db.add(Video(
                id=vid_a,
                title="Alice Investigated Video",
                filename="a_inv.mp4",
                original_filename="a_inv.mp4",
                file_path="storage/a_inv.mp4",
                uploaded_by=USER_A_ID,
                status="completed"
            ))
            await db.commit()
    run_async(setup_violence_data())

    resp_admin = client.get(f"/api/v1/violence/result/{vid_a}", headers=auth_headers(ADMIN_ID))
    assert resp_admin.status_code == 200

def test_idor_violence_status_blocked_for_cross_user():
    vid_a = uuid.uuid4()
    async def setup_video():
        async with SessionLocal() as db:
            db.add(Video(
                id=vid_a,
                title="Alice Processing Video",
                filename="a_proc.mp4",
                original_filename="a_proc.mp4",
                file_path="storage/a_proc.mp4",
                uploaded_by=USER_A_ID,
                status="processing"
            ))
            await db.commit()
    run_async(setup_video())

    resp_b = client.get(f"/api/v1/violence/status/{vid_a}", headers=auth_headers(USER_B_ID))
    assert resp_b.status_code == 404

def test_idor_reports_blocked_for_cross_user():
    rep_id = uuid.uuid4()
    async def setup_report():
        async with SessionLocal() as db:
            db.add(Report(
                id=rep_id,
                title="Alice Confidential Report",
                incident_type="Violence",
                data={"summary": "Classified", "created_by": str(USER_A_ID)}
            ))
            await db.commit()
    run_async(setup_report())

    resp_b = client.get(f"/api/v1/reports/{rep_id}", headers=auth_headers(USER_B_ID))
    assert resp_b.status_code == 404, f"IDOR fix: Expected 404 for cross-user, got {resp_b.status_code}"

def test_idor_reports_allowed_for_owner_and_admin():
    rep_id = uuid.uuid4()
    async def setup_report():
        async with SessionLocal() as db:
            db.add(Report(
                id=rep_id,
                title="Alice Incident Report",
                incident_type="Violence",
                data={"summary": "Case Summary", "created_by": str(USER_A_ID)}
            ))
            await db.commit()
    run_async(setup_report())

    resp_owner = client.get(f"/api/v1/reports/{rep_id}", headers=auth_headers(USER_A_ID))
    assert resp_owner.status_code == 200

    resp_admin = client.get(f"/api/v1/reports/{rep_id}", headers=auth_headers(ADMIN_ID))
    assert resp_admin.status_code == 200

# =========================================================================
# DOMAIN 6: SEC-05 ZIP SLIP REMEDIATION
# =========================================================================

def test_zip_slip_traversal_payload_rejected():
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("../../evil_traversal.jpg", b"MALICIOUS_BYTES")
    zip_buffer.seek(0)

    files = {"file": ("malicious_dataset.zip", zip_buffer.getvalue(), "application/zip")}
    resp = client.post("/api/v1/students/import/photos", files=files, headers=auth_headers(ADMIN_ID))
    assert resp.status_code == 400
    assert "Security violation" in resp.json()["detail"] or "path traversal" in resp.json()["detail"]

# =========================================================================
# DOMAIN 7: SEC-06 JWT LIFETIME AND REVOCATION
# =========================================================================

def test_token_lifetime_reduced_to_secure_duration():
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES <= 60, f"Token expiry {settings.ACCESS_TOKEN_EXPIRE_MINUTES} exceeds 60 min"

def test_revoked_token_rejected_after_logout():
    token = get_token_for(USER_A_ID)
    headers = {"Authorization": f"Bearer {token}"}

    # Verify token works initially
    pre_resp = client.get("/api/v1/auth/me", headers=headers)
    assert pre_resp.status_code == 200

    # Logout
    logout_resp = client.post("/api/v1/auth/logout", headers=headers)
    assert logout_resp.status_code == 200
    assert "revoked" in logout_resp.json()["message"].lower()

    # Verify token is now rejected
    post_resp = client.get("/api/v1/auth/me", headers=headers)
    assert post_resp.status_code == 401
    assert "revoked" in post_resp.json()["detail"].lower()

# =========================================================================
# DOMAIN 8: SEC-07 USER SIGNUP GOVERNANCE
# =========================================================================

def test_signup_unauthenticated_rejected():
    payload = {
        "email": f"attacker_{uuid.uuid4().hex[:6]}@campus.edu",
        "password": "Password123!",
        "full_name": "Rogue Attacker"
    }
    resp = client.post("/api/v1/auth/signup", json=payload)
    assert resp.status_code == 401

def test_signup_operator_rejected():
    payload = {
        "email": f"new_op_{uuid.uuid4().hex[:6]}@campus.edu",
        "password": "Password123!",
        "full_name": "New Operator"
    }
    resp = client.post("/api/v1/auth/signup", json=payload, headers=auth_headers(USER_A_ID))
    assert resp.status_code == 403

def test_signup_admin_allowed():
    payload = {
        "email": f"official_op_{uuid.uuid4().hex[:6]}@campus.edu",
        "password": "Password123!",
        "full_name": "Official Operator",
        "is_active": True
    }
    resp = client.post("/api/v1/auth/signup", json=payload, headers=auth_headers(ADMIN_ID))
    assert resp.status_code == 201
    assert resp.json()["email"] == payload["email"]

# =========================================================================
# DOMAIN 9: INPUT VALIDATION & DATABASE RESILIENCE
# =========================================================================

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

def test_db_sql_injection_resilient_via_orm():
    sqli_payload = "' OR 1=1; DROP TABLE users; --"
    resp = client.get(f"/api/v1/students?query={sqli_payload}", headers=auth_headers(USER_A_ID))
    assert resp.status_code == 200
    check_user = client.get("/api/v1/auth/me", headers=auth_headers(USER_A_ID))
    assert check_user.status_code == 200

# =========================================================================
# DOMAIN 10: FILE UPLOAD VALIDATION & API RESILIENCE
# =========================================================================

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

def test_api_password_hash_not_exposed_in_me():
    resp = client.get("/api/v1/auth/me", headers=auth_headers(USER_A_ID))
    assert resp.status_code == 200
    data = resp.json()
    assert "hashed_password" not in data
    assert "password" not in data

def test_api_cors_configuration():
    assert "http://localhost:5173" in settings.BACKEND_CORS_ORIGINS
    assert "*" not in settings.BACKEND_CORS_ORIGINS

# =========================================================================
# DOMAIN 11: WEBSOCKET SECURITY
# =========================================================================

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


def run_all_remediation_tests():
    test_functions = [
        # Auth
        ("test_auth_login_valid_credentials", test_auth_login_valid_credentials),
        ("test_auth_login_invalid_password", test_auth_login_invalid_password),
        ("test_auth_login_nonexistent_user", test_auth_login_nonexistent_user),
        ("test_auth_login_inactive_user", test_auth_login_inactive_user),
        ("test_auth_missing_token_rejected", test_auth_missing_token_rejected),
        ("test_auth_invalid_signature_rejected", test_auth_invalid_signature_rejected),
        ("test_auth_expired_token_rejected", test_auth_expired_token_rejected),
        ("test_auth_malformed_token_rejected", test_auth_malformed_token_rejected),
        ("test_auth_deleted_or_nonexistent_user_token_rejected", test_auth_deleted_or_nonexistent_user_token_rejected),
        ("test_auth_inactive_user_token_rejected", test_auth_inactive_user_token_rejected),
        # SEC-01 Storage
        ("test_storage_unauthenticated_request_rejected", test_storage_unauthenticated_request_rejected),
        ("test_storage_database_file_strictly_forbidden", test_storage_database_file_strictly_forbidden),
        ("test_storage_model_weights_strictly_forbidden", test_storage_model_weights_strictly_forbidden),
        ("test_storage_authenticated_valid_media_served", test_storage_authenticated_valid_media_served),
        # SEC-02 Secret Key
        ("test_jwt_cannot_be_forged_with_legacy_default_secret", test_jwt_cannot_be_forged_with_legacy_default_secret),
        ("test_active_secret_key_is_cryptographically_strong", test_active_secret_key_is_cryptographically_strong),
        # SEC-03 RBAC
        ("test_rbac_unauthenticated_requests_blocked", test_rbac_unauthenticated_requests_blocked),
        ("test_rbac_operator_cannot_delete_camera", test_rbac_operator_cannot_delete_camera),
        ("test_rbac_admin_can_delete_camera", test_rbac_admin_can_delete_camera),
        ("test_rbac_operator_cannot_delete_evidence", test_rbac_operator_cannot_delete_evidence),
        ("test_rbac_admin_can_delete_evidence", test_rbac_admin_can_delete_evidence),
        ("test_rbac_operator_cannot_create_camera", test_rbac_operator_cannot_create_camera),
        ("test_rbac_admin_can_create_camera", test_rbac_admin_can_create_camera),
        # SEC-04 IDOR
        ("test_idor_videos_endpoint_is_properly_isolated", test_idor_videos_endpoint_is_properly_isolated),
        ("test_idor_violence_result_blocked_for_cross_user", test_idor_violence_result_blocked_for_cross_user),
        ("test_idor_violence_result_allowed_for_owner", test_idor_violence_result_allowed_for_owner),
        ("test_idor_violence_result_allowed_for_admin", test_idor_violence_result_allowed_for_admin),
        ("test_idor_violence_status_blocked_for_cross_user", test_idor_violence_status_blocked_for_cross_user),
        ("test_idor_reports_blocked_for_cross_user", test_idor_reports_blocked_for_cross_user),
        ("test_idor_reports_allowed_for_owner_and_admin", test_idor_reports_allowed_for_owner_and_admin),
        # SEC-05 Zip Slip
        ("test_zip_slip_traversal_payload_rejected", test_zip_slip_traversal_payload_rejected),
        # SEC-06 Token Lifetime & Revocation
        ("test_token_lifetime_reduced_to_secure_duration", test_token_lifetime_reduced_to_secure_duration),
        ("test_revoked_token_rejected_after_logout", test_revoked_token_rejected_after_logout),
        # SEC-07 Signup Governance
        ("test_signup_unauthenticated_rejected", test_signup_unauthenticated_rejected),
        ("test_signup_operator_rejected", test_signup_operator_rejected),
        ("test_signup_admin_allowed", test_signup_admin_allowed),
        # Input Validation & DB
        ("test_input_malformed_uuid_returns_422", test_input_malformed_uuid_returns_422),
        ("test_input_malformed_json_body_returns_422", test_input_malformed_json_body_returns_422),
        ("test_input_missing_required_fields_returns_422", test_input_missing_required_fields_returns_422),
        ("test_db_sql_injection_resilient_via_orm", test_db_sql_injection_resilient_via_orm),
        # Upload & API Security
        ("test_upload_executable_extension_rejected", test_upload_executable_extension_rejected),
        ("test_upload_empty_video_rejected", test_upload_empty_video_rejected),
        ("test_api_password_hash_not_exposed_in_me", test_api_password_hash_not_exposed_in_me),
        ("test_api_cors_configuration", test_api_cors_configuration),
        # WebSocket
        ("test_ws_missing_token_rejected", test_ws_missing_token_rejected),
        ("test_ws_invalid_token_rejected", test_ws_invalid_token_rejected),
        ("test_ws_expired_token_rejected", test_ws_expired_token_rejected),
        ("test_ws_valid_token_authenticated", test_ws_valid_token_authenticated),
    ]

    print("=" * 70)
    print("PHASE 4A — SECURITY REMEDIATION & REGRESSION TEST SUITE")
    print("=" * 70)

    passed = 0
    failed = 0
    results = []

    for name, fn in test_functions:
        try:
            fn()
            print(f"  [PASS] {name}")
            passed += 1
            results.append({"test": name, "status": "PASSED"})
        except Exception as e:
            print(f"  [FAIL] {name} -> {str(e)}")
            failed += 1
            results.append({"test": name, "status": "FAILED", "error": str(e)})

    print("=" * 70)
    print(f"SUMMARY: {passed} PASSED, {failed} FAILED (Total: {len(test_functions)})")
    print("=" * 70)
    return passed, failed, results

if __name__ == "__main__":
    run_all_remediation_tests()
