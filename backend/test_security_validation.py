import os
import sys
import uuid
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

# Global test users - using alphanumeric UUIDs to avoid SQLite float parsing issue
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
        # User A: Operator
        user_a = User(
            id=USER_A_ID,
            email="operator_a@campus.edu",
            hashed_password=hashed,
            full_name="Operator Alice",
            is_active=True,
            role="operator"
        )
        # User B: Operator (peer)
        user_b = User(
            id=USER_B_ID,
            email="operator_b@campus.edu",
            hashed_password=hashed,
            full_name="Operator Bob",
            is_active=True,
            role="operator"
        )
        # User C: Admin
        user_admin = User(
            id=ADMIN_ID,
            email="admin@campus.edu",
            hashed_password=hashed,
            full_name="Admin Security Officer",
            is_active=True,
            role="admin"
        )
        # User D: Inactive
        user_inactive = User(
            id=INACTIVE_ID,
            email="inactive@campus.edu",
            hashed_password=hashed,
            full_name="Inactive Employee",
            is_active=False,
            role="operator"
        )
        # Global camera for incident FKs
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

# Initialize database
run_async(setup_test_db())

def get_token_for(user_id: uuid.UUID, role: str = "operator", expires_delta: timedelta = None) -> str:
    return security.create_access_token(user_id, expires_delta=expires_delta)

def auth_headers(user_id: uuid.UUID, role: str = "operator") -> dict:
    tok = get_token_for(user_id, role)
    return {"Authorization": f"Bearer {tok}"}

# =========================================================================
# STEP 1: AUTHENTICATION VALIDATION TESTS
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

def test_auth_logout_not_implemented():
    # Documents that no logout or token revocation API exists
    resp = client.post("/api/v1/auth/logout", headers=auth_headers(USER_A_ID))
    assert resp.status_code == 404 or resp.status_code == 405

# =========================================================================
# STEP 2: AUTHORIZATION / RBAC TESTS
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
        assert r.status_code == 401, f"{method} {path} should return 401 unauthenticated"

def test_rbac_operator_can_delete_camera_vulnerability():
    # Setup camera
    cam_id = uuid.uuid4()
    async def create_cam():
        async with SessionLocal() as db:
            db.add(Camera(
                id=cam_id,
                name=f"Test Cam {cam_id.hex[:6]}",
                building="Admin Block",
                floor=1,
                location="Quad",
                direction="North",
                resolution="1080p",
                status="active"
            ))
            await db.commit()
    run_async(create_cam())
    
    # Operator Alice sends DELETE /api/v1/cameras/{cam_id}
    resp = client.delete(f"/api/v1/cameras/{cam_id}", headers=auth_headers(USER_A_ID, role="operator"))
    # In strict RBAC this should be 403 Forbidden. In this system, it returns 200 OK.
    assert resp.status_code == 200, "Operator was able to delete camera (REST RBAC not enforced)"

def test_rbac_operator_can_delete_evidence_vulnerability():
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

    # Operator Bob sends DELETE /api/v1/evidence/{ev_id}
    resp = client.delete(f"/api/v1/evidence/{ev_id}", headers=auth_headers(USER_B_ID, role="operator"))
    assert resp.status_code == 204, "Operator was able to delete evidence (REST RBAC not enforced)"

# =========================================================================
# STEP 3: IDOR / OBJECT-LEVEL ACCESS TESTS
# =========================================================================

def test_idor_videos_endpoint_is_properly_isolated():
    # User A creates video
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

    # User B tries to GET /api/v1/videos/{vid_a}
    resp_b = client.get(f"/api/v1/videos/{vid_a}", headers=auth_headers(USER_B_ID))
    assert resp_b.status_code == 404, "User B should not access User A video via /videos/{id}"

    # User B tries to DELETE /api/v1/videos/{vid_a}
    del_b = client.delete(f"/api/v1/videos/{vid_a}", headers=auth_headers(USER_B_ID))
    assert del_b.status_code == 404, "User B should not delete User A video via /videos/{id}"

def test_idor_violence_result_vulnerable_cross_user_access():
    # Video belongs to User A
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

    # User B requests /api/v1/violence/result/{vid_a}
    resp_b = client.get(f"/api/v1/violence/result/{vid_a}", headers=auth_headers(USER_B_ID))
    # VULNERABILITY: Returns 200 and full dossier of User A's video
    assert resp_b.status_code == 200, "VULNERABILITY: User B accessed User A violence dossier via IDOR"
    assert resp_b.json()["video_id"] == str(vid_a)

def test_idor_reports_vulnerable_cross_user_access():
    rep_id = uuid.uuid4()
    async def setup_report():
        async with SessionLocal() as db:
            db.add(Report(
                id=rep_id,
                title="Alice Confidential Incident Report",
                incident_type="Violence",
                data={"summary": "Classified"}
            ))
            await db.commit()
    run_async(setup_report())

    # User B requests /api/v1/reports/{rep_id}
    resp_b = client.get(f"/api/v1/reports/{rep_id}", headers=auth_headers(USER_B_ID))
    assert resp_b.status_code == 200, "VULNERABILITY: User B accessed report generated by User A"
    assert resp_b.json()["title"] == "Alice Confidential Incident Report"

# =========================================================================
# STEP 4: INPUT VALIDATION TESTS
# =========================================================================

def test_input_malformed_uuid_returns_422():
    resp = client.get("/api/v1/cameras/not-a-valid-uuid", headers=auth_headers(USER_A_ID))
    assert resp.status_code == 422, "Malformed UUID in path should produce HTTP 422"

def test_input_malformed_json_body_returns_422():
    resp = client.post(
        "/api/v1/reports/generate",
        data="INVALID_JSON{{[",
        headers={"Content-Type": "application/json", **auth_headers(USER_A_ID)}
    )
    assert resp.status_code == 422, "Malformed JSON body should produce HTTP 422"

def test_input_missing_required_fields_returns_422():
    resp = client.post("/api/v1/cameras", json={"location": "Library"}, headers=auth_headers(USER_A_ID))
    assert resp.status_code == 422, "Missing required 'name' should produce HTTP 422"

# =========================================================================
# STEP 5: FILE UPLOAD SECURITY TESTS
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

def test_upload_path_traversal_filename_sanitized():
    # Attempt filename with path traversal
    traversal_name = "../../etc/shadow.mp4"
    files = {"file": (traversal_name, b"valid_simulated_bytes", "video/mp4")}
    resp = client.post("/api/v1/videos/upload", files=files, headers=auth_headers(USER_A_ID))
    # It rejects or creates random UUID filename, not writing to ../../etc/
    assert not os.path.exists("../../etc/shadow.mp4")

def test_static_storage_unauthenticated_file_exposure():
    # Verifies that static /storage mount exposes files (including active database files!) without authentication
    resp = client.get("/storage/test_security_audit.db")
    assert resp.status_code == 200, f"Expected 200 got {resp.status_code}"

# =========================================================================
# STEP 6: API SECURITY & DATA EXPOSURE TESTS
# =========================================================================

def test_api_password_hash_not_exposed_in_me():
    resp = client.get("/api/v1/auth/me", headers=auth_headers(USER_A_ID))
    assert resp.status_code == 200
    data = resp.json()
    assert "hashed_password" not in data, "Password hash must not be exposed in user response"
    assert "password" not in data

def test_api_cors_configuration():
    assert "http://localhost:5173" in settings.BACKEND_CORS_ORIGINS
    assert "*" not in settings.BACKEND_CORS_ORIGINS

# =========================================================================
# STEP 7: DATABASE SECURITY TESTS
# =========================================================================

def test_db_sql_injection_resilient_via_orm():
    # Passing SQL injection payload to student search
    sqli_payload = "' OR 1=1; DROP TABLE users; --"
    resp = client.get(f"/api/v1/students?query={sqli_payload}", headers=auth_headers(USER_A_ID))
    assert resp.status_code == 200
    # Confirm users table was NOT dropped
    check_user = client.get("/api/v1/auth/me", headers=auth_headers(USER_A_ID))
    assert check_user.status_code == 200, "SQL injection payload failed to breach ORM"

# =========================================================================
# STEP 8: SECRET MANAGEMENT TESTS
# =========================================================================

def test_secrets_default_secret_key_used():
    # Checks whether default fallback key is in use
    is_default = (settings.SECRET_KEY == "SUPER_SECRET_REPLACE_THIS_IN_PRODUCTION")
    # This test asserts True to confirm the vulnerability is verified and flagged
    assert is_default is True, "FINDING: Default insecure SECRET_KEY is active in settings"

def test_secrets_excessive_token_lifetime():
    # 7 days is 10,080 minutes
    assert settings.ACCESS_TOKEN_EXPIRE_MINUTES >= 10080, "FINDING: Token expiration is 7 days (excessively long)"

# =========================================================================
# STEP 9: WEBSOCKET SECURITY TESTS
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


def run_all_security_tests():
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
        ("test_auth_logout_not_implemented", test_auth_logout_not_implemented),
        # RBAC
        ("test_rbac_unauthenticated_requests_blocked", test_rbac_unauthenticated_requests_blocked),
        ("test_rbac_operator_can_delete_camera_vulnerability", test_rbac_operator_can_delete_camera_vulnerability),
        ("test_rbac_operator_can_delete_evidence_vulnerability", test_rbac_operator_can_delete_evidence_vulnerability),
        # IDOR
        ("test_idor_videos_endpoint_is_properly_isolated", test_idor_videos_endpoint_is_properly_isolated),
        ("test_idor_violence_result_vulnerable_cross_user_access", test_idor_violence_result_vulnerable_cross_user_access),
        ("test_idor_reports_vulnerable_cross_user_access", test_idor_reports_vulnerable_cross_user_access),
        # Input
        ("test_input_malformed_uuid_returns_422", test_input_malformed_uuid_returns_422),
        ("test_input_malformed_json_body_returns_422", test_input_malformed_json_body_returns_422),
        ("test_input_missing_required_fields_returns_422", test_input_missing_required_fields_returns_422),
        # Upload
        ("test_upload_path_traversal_filename_sanitized", test_upload_path_traversal_filename_sanitized),
        ("test_upload_executable_extension_rejected", test_upload_executable_extension_rejected),
        ("test_upload_empty_video_rejected", test_upload_empty_video_rejected),
        ("test_static_storage_unauthenticated_file_exposure", test_static_storage_unauthenticated_file_exposure),
        # API Security
        ("test_api_password_hash_not_exposed_in_me", test_api_password_hash_not_exposed_in_me),
        ("test_api_cors_configuration", test_api_cors_configuration),
        # Database
        ("test_db_sql_injection_resilient_via_orm", test_db_sql_injection_resilient_via_orm),
        # Secrets
        ("test_secrets_default_secret_key_used", test_secrets_default_secret_key_used),
        ("test_secrets_excessive_token_lifetime", test_secrets_excessive_token_lifetime),
        # WebSocket
        ("test_ws_missing_token_rejected", test_ws_missing_token_rejected),
        ("test_ws_invalid_token_rejected", test_ws_invalid_token_rejected),
        ("test_ws_expired_token_rejected", test_ws_expired_token_rejected),
        ("test_ws_valid_token_authenticated", test_ws_valid_token_authenticated),
    ]

    print("=" * 70)
    print("PHASE 4 — SECURITY & ACCESS CONTROL VALIDATION SUITE")
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
    run_all_security_tests()
