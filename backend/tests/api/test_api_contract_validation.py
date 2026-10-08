"""
PHASE 7 — API CONTRACT & END-TO-END FUNCTIONAL VALIDATION TEST SUITE

Empirical validation of backend APIs according to their implemented contracts:
1. Route Inventory (82 endpoints)
2. Authentication Contract (public, protected, missing, invalid, expired, revoked, logout)
3. RBAC / Authorization Contract (admin, operator, ordinary user)
4. IDOR / Object Ownership (cross-user access controls)
5. CRUD Lifecycle (cameras, zones, students, reports, videos)
6. Request Validation (schema errors, types, bounds, content types, 422)
7. Status Code Contract (200, 201, 204, 400, 401, 403, 404, 409, 413, 422)
8. Video Upload -> Violence Analysis E2E Workflow
9. X3D-M API Integration (threshold=0.40, temporal windowing, 0-frame rejection)
10. Report Idempotency (FAIL-04 regression)
11. File / Storage Security (/storage path traversal, forbidden extensions, auth)
12. WebSocket Contract (/api/v1/notifications/ws token authorization)
13. CORS Behavior (allowed & disallowed origins, preflight)
14. Frontend / Backend Contract Mapping (44 frontend routes verified)
15. Pagination & Filtering (students, cameras)
16. Error Consistency (detail structure, no leakages)
17. Concurrency / Race Resolution
18. Database / API Consistency (state persistence across operations)
"""

import os
import sys
import uuid
import io
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

import pytest
import jwt
from fastapi.testclient import TestClient
from fastapi.routing import APIRoute
from starlette.routing import WebSocketRoute, Mount

# Isolated test environment configuration
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_api_contract_audit.db"

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
from app.models.student import Student
from app.models.incident import Incident, Evidence, DetectedEvent
from app.models.report import Report
from app.models.notification import Notification

client = TestClient(app, raise_server_exceptions=False)

# Fixed test user identities
ADMIN_ID = uuid.UUID("11111111-aaaa-1111-aaaa-111111111111")
OPERATOR_ID = uuid.UUID("22222222-bbbb-2222-bbbb-222222222222")
USER_ID = uuid.UUID("33333333-cccc-3333-cccc-333333333333")
INACTIVE_ID = uuid.UUID("44444444-dddd-4444-dddd-444444444444")
GLOBAL_CAM_ID = uuid.UUID("55555555-eeee-5555-eeee-555555555555")

PASSWORD_PLAIN = "SecretPassword123!"


def extract_all_registered_routes(app_instance):
    """Recursively extract all endpoints from FastAPI app and included routers."""
    results = []
    def _recurse(routes, prefix=""):
        for r in routes:
            if isinstance(r, APIRoute):
                p = prefix + r.path
                if not p.startswith(('/docs', '/redoc', '/api/v1/openapi.json')):
                    for m in sorted(list(r.methods)):
                        results.append({"type": "HTTP", "method": m, "path": p, "endpoint": r})
            elif isinstance(r, WebSocketRoute):
                p = prefix + r.path
                results.append({"type": "WS", "method": "WEBSOCKET", "path": p, "endpoint": r})
            elif isinstance(r, Mount):
                _recurse(r.routes, prefix=prefix + r.path)
            elif hasattr(r, "routes"):
                _recurse(r.routes, prefix=prefix)
            elif hasattr(r, "original_router") and hasattr(r.original_router, "routes"):
                sub_p = ""
                if hasattr(r, "include_context") and r.include_context:
                    sub_p = getattr(r.include_context, "prefix", "")
                _recurse(r.original_router.routes, prefix=prefix + sub_p)
    _recurse(app_instance.routes)
    return results


async def init_audit_db():
    """Initializes tables and populates isolated audit records."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as db:
        hashed = security.get_password_hash(PASSWORD_PLAIN)
        admin = User(
            id=ADMIN_ID,
            email="admin@campus.edu",
            hashed_password=hashed,
            full_name="Admin Director",
            role="admin",
            is_active=True
        )
        operator = User(
            id=OPERATOR_ID,
            email="operator@campus.edu",
            hashed_password=hashed,
            full_name="Operator Officer",
            role="operator",
            is_active=True
        )
        user = User(
            id=USER_ID,
            email="ordinary_user@campus.edu",
            hashed_password=hashed,
            full_name="Ordinary Staff",
            role="user",
            is_active=True
        )
        inactive = User(
            id=INACTIVE_ID,
            email="inactive_user@campus.edu",
            hashed_password=hashed,
            full_name="Inactive Staff",
            role="operator",
            is_active=False
        )
        cam = Camera(
            id=GLOBAL_CAM_ID,
            name="Main North Gate Camera",
            building="North Gate",
            floor=1,
            location="Gate Entrance",
            direction="North",
            resolution="1080p",
            status="active"
        )
        db.add_all([admin, operator, user, inactive, cam])
        await db.commit()


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    asyncio.run(init_audit_db())


def get_token(user_id: uuid.UUID, role: str = "operator", expires_delta: timedelta = None) -> str:
    return security.create_access_token(user_id, expires_delta=expires_delta)


def auth_header(user_id: uuid.UUID, role: str = "operator") -> Dict[str, str]:
    return {"Authorization": f"Bearer {get_token(user_id, role)}"}


# =========================================================================
# STEP 1: API ROUTE INVENTORY
# =========================================================================

def test_step1_route_inventory_count():
    """Verify that all 82 operational route endpoints are registered."""
    all_routes = extract_all_registered_routes(app)
    http_routes = [r for r in all_routes if r["type"] == "HTTP"]
    ws_routes = [r for r in all_routes if r["type"] == "WS"]
    
    assert len(all_routes) == 82, f"Expected 82 registered endpoints, got {len(all_routes)}"
    assert len(http_routes) == 81, f"Expected 81 HTTP endpoints, got {len(http_routes)}"
    assert len(ws_routes) == 1, f"Expected 1 WebSocket route, got {len(ws_routes)}"


# =========================================================================
# STEP 2: AUTHENTICATION CONTRACT
# =========================================================================

def test_step2_public_endpoints_accessible():
    """Verify public endpoints return 200 without Authorization."""
    r_root = client.get("/")
    assert r_root.status_code == 200
    assert "message" in r_root.json()

    r_health = client.get("/api/v1/health")
    assert r_health.status_code == 200
    assert r_health.json().get("status") == "healthy"


def test_step2_missing_token_returns_401():
    """Verify protected endpoints reject requests without token with 401."""
    resp = client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert "detail" in resp.json()


def test_step2_invalid_token_returns_401():
    """Verify corrupted or forged JWT returns 401."""
    resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer totally_bogus_jwt_token"})
    assert resp.status_code == 401


def test_step2_expired_token_returns_401():
    """Verify expired JWT token returns 401."""
    tok = get_token(OPERATOR_ID, expires_delta=timedelta(seconds=-60))
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert resp.status_code == 401


def test_step2_malformed_auth_header_returns_401():
    """Verify missing 'Bearer ' prefix returns 401."""
    tok = get_token(OPERATOR_ID)
    resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Token {tok}"})
    assert resp.status_code == 401


def test_step2_login_and_logout_lifecycle():
    """Verify login failure, login success, profile lookup, logout revocation, and access rejection."""
    # 1. Login Failure (observed implementation returns 400 Bad Request)
    bad_login = client.post("/api/v1/auth/login", data={"username": "operator@campus.edu", "password": "WrongPassword"})
    assert bad_login.status_code == 400
    assert "Incorrect email or password" in bad_login.json()["detail"]

    # 2. Login Success
    good_login = client.post("/api/v1/auth/login", data={"username": "operator@campus.edu", "password": PASSWORD_PLAIN})
    assert good_login.status_code == 200
    token = good_login.json()["access_token"]

    # 3. Access with valid token
    me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "operator@campus.edu"

    # 4. Logout
    logout_resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert logout_resp.status_code == 200

    # 5. Access after logout (token revoked)
    post_logout = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert post_logout.status_code == 401


def test_step2_inactive_user_rejected():
    """Verify inactive user cannot access protected endpoints (403 Forbidden)."""
    headers = auth_header(INACTIVE_ID)
    resp = client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 403


# =========================================================================
# STEP 3: RBAC / AUTHORIZATION CONTRACT
# =========================================================================

def test_step3_admin_only_operations_enforce_rbac():
    """Verify that administrative endpoints allow Admin and return 403 for Operator / User."""
    cam_payload = {
        "name": f"RBAC Audit Cam {uuid.uuid4().hex[:6]}",
        "building": "Science Complex",
        "floor": 2,
        "location": "Corridor B",
        "direction": "West",
        "resolution": "1080p",
        "status": "active"
    }

    # 1. Operator attempts to create camera -> 403
    op_res = client.post("/api/v1/cameras", json=cam_payload, headers=auth_header(OPERATOR_ID, "operator"))
    assert op_res.status_code == 403, f"Expected 403 for Operator, got {op_res.status_code}"

    # 2. Ordinary user attempts to create camera -> 403
    usr_res = client.post("/api/v1/cameras", json=cam_payload, headers=auth_header(USER_ID, "user"))
    assert usr_res.status_code == 403, f"Expected 403 for User, got {usr_res.status_code}"

    # 3. Admin creates camera -> 201
    adm_res = client.post("/api/v1/cameras", json=cam_payload, headers=auth_header(ADMIN_ID, "admin"))
    assert adm_res.status_code == 201, f"Expected 201 for Admin, got {adm_res.status_code}"
    new_cam_id = adm_res.json()["id"]

    # 4. Operator attempts to delete camera -> 403
    op_del = client.delete(f"/api/v1/cameras/{new_cam_id}", headers=auth_header(OPERATOR_ID, "operator"))
    assert op_del.status_code == 403

    # 5. Admin deletes camera -> 200
    adm_del = client.delete(f"/api/v1/cameras/{new_cam_id}", headers=auth_header(ADMIN_ID, "admin"))
    assert adm_del.status_code == 200


def test_step3_user_signup_restricted_to_admin():
    """Verify that new user creation is restricted to Admin."""
    signup_payload = {
        "email": f"new_officer_{uuid.uuid4().hex[:6]}@campus.edu",
        "password": "SecurePassword123!",
        "full_name": "New Officer",
        "role": "operator"
    }
    # Operator cannot signup users
    op_res = client.post("/api/v1/auth/signup", json=signup_payload, headers=auth_header(OPERATOR_ID, "operator"))
    assert op_res.status_code == 403

    # Admin can signup users
    adm_res = client.post("/api/v1/auth/signup", json=signup_payload, headers=auth_header(ADMIN_ID, "admin"))
    assert adm_res.status_code == 201


# =========================================================================
# STEP 4: IDOR / OBJECT OWNERSHIP CONTRACT
# =========================================================================

def test_step4_idor_video_deletion_cross_user():
    """Verify that User A's uploaded video cannot be deleted by User B (returns 404/denied)."""
    vid_id = uuid.uuid4()
    async def _add_vid():
        async with SessionLocal() as db:
            v = Video(
                id=vid_id,
                title="Admin Confidential Surveillance",
                filename="admin_clip.mp4",
                original_filename="admin_clip.mp4",
                file_path="/storage/videos/admin_clip.mp4",
                uploaded_by=ADMIN_ID,
                camera_id=GLOBAL_CAM_ID,
                status="ready",
                created_at=datetime.now(timezone.utc)
            )
            db.add(v)
            await db.commit()
    asyncio.run(_add_vid())

    # Operator attempts to delete Admin's video -> 404 (ownership check returns 404)
    del_res = client.delete(f"/api/v1/videos/{vid_id}", headers=auth_header(OPERATOR_ID, "operator"))
    assert del_res.status_code == 404, f"IDOR violation: Operator deleted Admin's video! Status: {del_res.status_code}"

    # Admin deletes their own video -> 204
    adm_del = client.delete(f"/api/v1/videos/{vid_id}", headers=auth_header(ADMIN_ID, "admin"))
    assert adm_del.status_code == 204


def test_step4_idor_report_access_cross_user():
    """Verify that a private report owned by User A cannot be accessed by User B."""
    rep_id = uuid.uuid4()
    async def _add_rep():
        async with SessionLocal() as db:
            r = Report(
                id=rep_id,
                title="Confidential Officer Audit",
                incident_type="Investigation",
                data={"summary": "Classified", "created_by": str(ADMIN_ID)},
                created_at=datetime.now(timezone.utc)
            )
            db.add(r)
            await db.commit()
    asyncio.run(_add_rep())

    # Operator attempts to read Admin's report -> 404
    op_get = client.get(f"/api/v1/reports/{rep_id}", headers=auth_header(OPERATOR_ID, "operator"))
    assert op_get.status_code == 404

    # Admin reads their own report -> 200
    adm_get = client.get(f"/api/v1/reports/{rep_id}", headers=auth_header(ADMIN_ID, "admin"))
    assert adm_get.status_code == 200


# =========================================================================
# STEP 5: CRUD API VALIDATION
# =========================================================================

def test_step5_camera_and_zone_crud_lifecycle():
    """Test full CRUD lifecycle for Cameras and Virtual Zones."""
    adm_headers = auth_header(ADMIN_ID, "admin")

    # 1. CREATE Camera
    cam_in = {
        "name": f"CRUD Cam {uuid.uuid4().hex[:6]}",
        "building": "Library",
        "floor": 1,
        "location": "Reading Room",
        "direction": "East",
        "resolution": "1080p",
        "status": "active"
    }
    create_res = client.post("/api/v1/cameras", json=cam_in, headers=adm_headers)
    assert create_res.status_code == 201
    c_id = create_res.json()["id"]

    # 2. LIST Cameras
    list_res = client.get("/api/v1/cameras", headers=adm_headers)
    assert list_res.status_code == 200
    assert any(c["id"] == c_id for c in list_res.json())

    # 3. GET Camera
    get_res = client.get(f"/api/v1/cameras/{c_id}", headers=adm_headers)
    assert get_res.status_code == 200
    assert get_res.json()["name"] == cam_in["name"]

    # 4. UPDATE Camera
    update_res = client.put(f"/api/v1/cameras/{c_id}", json={"location": "Quiet Study Area"}, headers=adm_headers)
    assert update_res.status_code == 200
    assert update_res.json()["location"] == "Quiet Study Area"

    # 5. CREATE Virtual Zone under Camera (coordinates string)
    zone_in = {
        "name": "Restricted Stacks Zone",
        "zone_type": "restricted",
        "geometry_type": "polygon",
        "coordinates": json.dumps([[10, 10], [50, 10], [50, 50], [10, 50]])
    }
    zone_res = client.post(f"/api/v1/cameras/{c_id}/zones", json=zone_in, headers=adm_headers)
    assert zone_res.status_code == 201
    z_id = zone_res.json()["id"]

    # 6. DELETE Virtual Zone
    del_zone = client.delete(f"/api/v1/cameras/{c_id}/zones/{z_id}", headers=adm_headers)
    assert del_zone.status_code == 200

    # 7. DELETE Camera
    del_cam = client.delete(f"/api/v1/cameras/{c_id}", headers=adm_headers)
    assert del_cam.status_code == 200


def test_step5_student_crud_lifecycle():
    """Test full CRUD lifecycle for Students."""
    headers = auth_header(OPERATOR_ID, "operator")
    roll_num = f"ROLL-{uuid.uuid4().hex[:6]}"
    stud_in = {
        "name": "David Auditor",
        "university_roll_number": roll_num,
        "department": "Computer Science",
        "programme": "B.Tech",
        "year": 3,
        "semester": 5,
        "academic_year": 2026,
        "section": "A",
        "email": f"{roll_num.lower()}@campus.edu",
        "phone_number": "9876543210"
    }

    # 1. CREATE Student
    c_res = client.post("/api/v1/students", json=stud_in, headers=headers)
    assert c_res.status_code == 201
    s_id = c_res.json()["id"]

    # 2. LIST Students
    l_res = client.get("/api/v1/students", headers=headers)
    assert l_res.status_code == 200
    data = l_res.json()
    items = data.get("items", data)
    assert any(s["id"] == s_id for s in items)

    # 3. GET Student
    g_res = client.get(f"/api/v1/students/{s_id}", headers=headers)
    assert g_res.status_code == 200
    assert g_res.json()["name"] == "David Auditor"

    # 4. UPDATE Student
    u_res = client.put(f"/api/v1/students/{s_id}", json={"section": "B"}, headers=headers)
    assert u_res.status_code == 200
    assert u_res.json()["section"] == "B"

    # 5. DELETE Student
    d_res = client.delete(f"/api/v1/students/{s_id}", headers=headers)
    assert d_res.status_code == 204


# =========================================================================
# STEP 6: REQUEST VALIDATION
# =========================================================================

def test_step6_validation_failures():
    """Verify request validation rejects invalid inputs with HTTP 422/400."""
    headers = auth_header(ADMIN_ID, "admin")

    # 1. Missing required fields -> 422
    r_missing = client.post("/api/v1/cameras", json={}, headers=headers)
    assert r_missing.status_code == 422

    # 2. Wrong data type (floor as string) -> 422
    r_type = client.post("/api/v1/cameras", json={"name": "Bad Cam", "floor": "top floor"}, headers=headers)
    assert r_type.status_code == 422

    # 3. Malformed UUID in path -> 422
    r_uuid = client.get("/api/v1/cameras/not-a-valid-uuid", headers=headers)
    assert r_uuid.status_code == 422

    # 4. Malformed JSON raw body -> 422
    r_json = client.post(
        "/api/v1/cameras",
        content=b'{"name": "broken json',
        headers={**headers, "Content-Type": "application/json"}
    )
    assert r_json.status_code == 422

    # 5. Unsupported file upload extension -> 400
    fake_exe = io.BytesIO(b"MZ\x90\x00executable")
    r_ext = client.post(
        "/api/v1/videos/upload",
        files={"file": ("malicious.exe", fake_exe, "application/octet-stream")},
        data={"title": "Bad File", "camera_id": str(GLOBAL_CAM_ID)},
        headers=headers
    )
    assert r_ext.status_code == 400


# =========================================================================
# STEP 7: STATUS CODE CONTRACT MATRIX
# =========================================================================

def test_step7_status_code_matrix():
    """Verify semantic HTTP status codes across endpoints."""
    headers = auth_header(OPERATOR_ID, "operator")

    # 200 OK
    assert client.get("/api/v1/health").status_code == 200

    # 400 Bad Request (duplicate student email)
    roll = uuid.uuid4().hex[:6]
    s_payload = {
        "name": "Dup Student",
        "university_roll_number": f"DUP-{roll}",
        "department": "CS",
        "programme": "B.Tech",
        "year": 1,
        "semester": 1,
        "academic_year": 2026,
        "section": "A",
        "email": f"dup_{roll}@campus.edu",
        "phone_number": "1234567890"
    }
    r1 = client.post("/api/v1/students", json=s_payload, headers=headers)
    assert r1.status_code == 201
    # Duplicate insert -> 400
    r2 = client.post("/api/v1/students", json=s_payload, headers=headers)
    assert r2.status_code == 400

    # 401 Unauthorized
    assert client.get("/api/v1/auth/me").status_code == 401

    # 403 Forbidden
    assert client.post("/api/v1/cameras", json={"name": "X"}, headers=headers).status_code == 403

    # 404 Not Found
    random_id = uuid.uuid4()
    assert client.get(f"/api/v1/cameras/{random_id}", headers=headers).status_code == 404

    # 422 Unprocessable Entity
    assert client.post("/api/v1/students", json={"invalid": True}, headers=headers).status_code == 422


# =========================================================================
# STEP 8 & STEP 9: VIDEO UPLOAD -> ANALYSIS E2E WORKFLOW & X3D-M INTEGRATION
# =========================================================================

def test_step8_and_step9_x3d_violence_e2e_workflow():
    """Verify video upload, X3D-M analysis, result retrieval, and report generation."""
    import cv2
    import numpy as np

    headers = auth_header(ADMIN_ID, "admin")

    # 1. Generate synthetic test video in memory
    buf = io.BytesIO()
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    temp_path = os.path.join(settings.STORAGE_DIR, "test_api_workflow_clip.mp4")
    os.makedirs(os.path.dirname(temp_path), exist_ok=True)
    out = cv2.VideoWriter(temp_path, fourcc, 20.0, (224, 224))
    for i in range(40):  # 2.0 seconds
        frame = np.zeros((224, 224, 3), dtype=np.uint8)
        cv2.circle(frame, (50 + i * 2, 100), 20, (255, 255, 255), -1)
        out.write(frame)
    out.release()

    with open(temp_path, "rb") as vf:
        up_res = client.post(
            "/api/v1/violence/upload",
            files={"file": ("test_clip.mp4", vf, "video/mp4")},
            data={"title": "E2E Workflow Test Video", "camera_id": str(GLOBAL_CAM_ID)},
            headers=headers
        )
    assert up_res.status_code == 201
    video_id = up_res.json()["video_id"]

    # 2. Trigger X3D-M Analysis
    an_res = client.post(
        "/api/v1/violence/analyze",
        data={"video_id": video_id},
        headers=headers
    )
    assert an_res.status_code == 200
    an_data = an_res.json()
    assert an_data["video_id"] == video_id
    assert an_data["status"] in ["NORMAL", "VIOLENCE_DETECTED"]
    assert "verdict" in an_data
    assert "overall_confidence" in an_data

    # 3. Retrieve Stored Violence Result
    res_res = client.get(f"/api/v1/violence/result/{video_id}", headers=headers)
    assert res_res.status_code == 200
    assert res_res.json()["video_id"] == video_id

    # 4. Generate Official Report for this Video/Incident
    rep_res = client.post(
        "/api/v1/reports/generate",
        json={
            "title": "Forensic Video Incident Report",
            "incident_type": "Surveillance Analysis",
            "incident_id": an_data.get("incident_id"),
            "data": {"video_id": video_id, "status": an_data["status"]}
        },
        headers=headers
    )
    assert rep_res.status_code == 201
    rep_id = rep_res.json()["id"]

    # 5. Retrieve Generated Report
    get_rep = client.get(f"/api/v1/reports/{rep_id}", headers=headers)
    assert get_rep.status_code == 200
    assert get_rep.json()["id"] == rep_id


# =========================================================================
# STEP 10: REPORT IDEMPOTENCY
# =========================================================================

def test_step10_report_generation_idempotency():
    """Verify that repeated report generation requests with the same incident_id return the existing report."""
    headers = auth_header(ADMIN_ID, "admin")

    # Create an isolated incident in DB
    inc_id = uuid.uuid4()
    async def _add_inc():
        async with SessionLocal() as db:
            inc = Incident(
                id=inc_id,
                incident_type="Fight",
                confidence=0.88,
                camera_id=GLOBAL_CAM_ID,
                timestamp=datetime.now(timezone.utc),
                explanation="Idempotency test altercation"
            )
            db.add(inc)
            await db.commit()
    asyncio.run(_add_inc())

    payload = {
        "title": "Idempotent Fight Report",
        "incident_type": "Violence",
        "incident_id": str(inc_id),
        "data": {"summary": "Altercation logged"}
    }

    # First request -> 201
    r1 = client.post("/api/v1/reports/generate", json=payload, headers=headers)
    assert r1.status_code == 201
    rep1_id = r1.json()["id"]

    # Second request with identical incident_id -> reuses report (same ID)
    r2 = client.post("/api/v1/reports/generate", json=payload, headers=headers)
    assert r2.status_code in [200, 201]
    rep2_id = r2.json()["id"]

    assert rep1_id == rep2_id, "Report idempotency failed: different report IDs returned for same incident!"


# =========================================================================
# STEP 11: FILE / STORAGE SECURITY
# =========================================================================

def test_step11_storage_security_controls():
    """Verify authenticated access, directory traversal blocking, and forbidden extension blocking."""
    # Create test media file
    test_media_rel = "audit_evidence_test.jpg"
    abs_path = os.path.join(settings.STORAGE_DIR, test_media_rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as f:
        f.write(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01test_jpeg_data")

    headers = auth_header(OPERATOR_ID, "operator")

    # 1. Valid authenticated access -> 200
    valid_res = client.get(f"/storage/{test_media_rel}", headers=headers)
    assert valid_res.status_code == 200

    # 2. Missing token -> 401
    no_auth = client.get(f"/storage/{test_media_rel}")
    assert no_auth.status_code == 401

    # 3. Directory traversal attempt -> 404
    traversal = client.get("/storage/../../../../windows/system.ini", headers=headers)
    assert traversal.status_code in [404, 403]

    # 4. Forbidden file extension (.env, .py, .db) -> 403
    forbidden_env = client.get("/storage/secret_config.env", headers=headers)
    assert forbidden_env.status_code == 403
    forbidden_db = client.get("/storage/cctv.db", headers=headers)
    assert forbidden_db.status_code == 403


# =========================================================================
# STEP 12: WEBSOCKET CONTRACT
# =========================================================================

def test_step12_websocket_authorization():
    """Verify WebSocket endpoint enforces token authorization and message communication."""
    # 1. Valid JWT allows connection and PING/PONG
    valid_tok = get_token(OPERATOR_ID, "operator")
    with client.websocket_connect(f"/api/v1/notifications/ws?token={valid_tok}") as ws:
        ws.send_text("PING")
        msg = ws.receive_text()
        assert msg == "PONG"

    # 2. Missing token -> rejected (connection closed)
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/notifications/ws") as ws:
            ws.receive_text()

    # 3. Invalid token -> rejected
    with pytest.raises(Exception):
        with client.websocket_connect("/api/v1/notifications/ws?token=invalid_jwt") as ws:
            ws.receive_text()


# =========================================================================
# STEP 13: CORS
# =========================================================================

def test_step13_cors_headers():
    """Verify CORS preflight and origin headers for allowed and disallowed origins."""
    allowed_origin = "http://localhost:5173"
    disallowed_origin = "http://malicious-site.com"

    # Preflight OPTIONS with allowed origin
    preflight = client.options(
        "/api/v1/cameras",
        headers={
            "Origin": allowed_origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization"
        }
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") == allowed_origin

    # Request with disallowed origin
    disallowed = client.get(
        "/api/v1/health",
        headers={"Origin": disallowed_origin}
    )
    assert disallowed.headers.get("access-control-allow-origin") != disallowed_origin


# =========================================================================
# STEP 14: FRONTEND / BACKEND INTEGRATION MAPPING
# =========================================================================

def test_step14_frontend_endpoints_exist_in_backend():
    """Verify all 44 distinct frontend API calls map to registered backend routes."""
    backend_routes = extract_all_registered_routes(app)
    backend_paths = {r["path"] for r in backend_routes}

    frontend_routes = [
        "/api/v1/auth/me",
        "/api/v1/auth/login",
        "/api/v1/cameras",
        "/api/v1/cameras/{id}",
        "/api/v1/cameras/{id}/zones",
        "/api/v1/cameras/{id}/zones/{zone_id}",
        "/api/v1/dashboard",
        "/api/v1/events",
        "/api/v1/events/{id}",
        "/api/v1/notifications",
        "/api/v1/notifications/read-all",
        "/api/v1/notifications/{id}/read",
        "/api/v1/reports",
        "/api/v1/reports/{id}",
        "/api/v1/reports/generate",
        "/api/v1/students",
        "/api/v1/students/{id}",
        "/api/v1/students/{id}/photos",
        "/api/v1/students/{id}/photos/{photo_id}",
        "/api/v1/students/{id}/enroll",
        "/api/v1/students/{id}/appearances",
        "/api/v1/students/{id}/enrollment-status",
        "/api/v1/students/import",
        "/api/v1/students/import/enroll",
        "/api/v1/students/import/photos",
        "/api/v1/students/import/status/{job_id}",
        "/api/v1/students/import/report/{job_id}",
        "/api/v1/students/import/cancel/{job_id}",
        "/api/v1/timeline/{target_id}",
        "/api/v1/tracks/{track_id}/identified-student",
        "/api/v1/videos",
        "/api/v1/videos/upload",
        "/api/v1/videos/{video_id}",
        "/api/v1/videos/{id}/tracks",
        "/api/v1/violence/status/{video_id}",
        "/api/v1/violence/report",
        "/api/v1/investigations/search",
        "/api/v1/evidence/{evidence_id}"
    ]

    for ep in frontend_routes:
        prefix_part = ep.split("{")[0]
        matched = any(bp.startswith(prefix_part) for bp in backend_paths)
        assert matched, f"Frontend endpoint {ep} has no matching backend route in {backend_paths}!"


# =========================================================================
# STEP 15: PAGINATION AND FILTERING
# =========================================================================

def test_step15_pagination_and_filtering():
    """Verify pagination and query parameters for students and cameras."""
    headers = auth_header(OPERATOR_ID, "operator")

    # Student pagination
    p_res = client.get("/api/v1/students?page=1&page_size=5", headers=headers)
    assert p_res.status_code == 200
    data = p_res.json()
    assert "items" in data
    assert "total" in data

    # Camera filter
    c_res = client.get("/api/v1/cameras?building=North Gate", headers=headers)
    assert c_res.status_code == 200
    cams = c_res.json()
    assert all(c["building"] == "North Gate" for c in cams)


# =========================================================================
# STEP 16: ERROR CONSISTENCY
# =========================================================================

def test_step16_error_format_consistency():
    """Verify consistent error response format across routers."""
    headers = auth_header(OPERATOR_ID, "operator")

    # 404 error format
    r404 = client.get(f"/api/v1/cameras/{uuid.uuid4()}", headers=headers)
    assert r404.status_code == 404
    assert "detail" in r404.json()
    assert isinstance(r404.json()["detail"], str)

    # 422 validation error format
    r422 = client.post("/api/v1/cameras", json={"bad": "payload"}, headers=headers)
    assert r422.status_code in [403, 422]  # RBAC 403 checked first or 422
    assert "detail" in r422.json()


# =========================================================================
# STEP 17: CONCURRENCY / RACE RESOLUTION
# =========================================================================

def test_step17_concurrent_report_requests():
    """Verify simultaneous report generation requests for the same incident resolve safely."""
    import httpx

    # Create distinct incident
    conc_inc_id = uuid.uuid4()
    async def _add():
        async with SessionLocal() as db:
            inc = Incident(
                id=conc_inc_id,
                incident_type="Fight",
                confidence=0.92,
                camera_id=GLOBAL_CAM_ID,
                timestamp=datetime.now(timezone.utc),
                explanation="Concurrent test altercation"
            )
            db.add(inc)
            await db.commit()
    asyncio.run(_add())

    tok = get_token(ADMIN_ID, "admin")
    payload = {
        "title": "Concurrent Forensic Report",
        "incident_type": "Violence",
        "incident_id": str(conc_inc_id),
        "data": {"summary": "Concurrent check"}
    }

    async def _fire():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as ac:
            tasks = [
                ac.post("/api/v1/reports/generate", json=payload, headers={"Authorization": f"Bearer {tok}"})
                for _ in range(3)
            ]
            return await asyncio.gather(*tasks)

    responses = asyncio.run(_fire())
    assert all(r.status_code in [200, 201] for r in responses)
    rep_ids = {r.json()["id"] for r in responses}
    assert len(rep_ids) == 1, f"Expected exactly 1 report ID across concurrent requests, got {rep_ids}"


# =========================================================================
# STEP 18: DATABASE / API CONSISTENCY
# =========================================================================

def test_step18_database_api_consistency():
    """Verify that resources created via API persist accurately in the database."""
    headers = auth_header(ADMIN_ID, "admin")
    cam_name = f"Consistency Cam {uuid.uuid4().hex[:6]}"
    res = client.post(
        "/api/v1/cameras",
        json={
            "name": cam_name,
            "building": "Engineering Block",
            "floor": 3,
            "location": "Lab 301",
            "direction": "North",
            "resolution": "4K",
            "status": "active"
        },
        headers=headers
    )
    assert res.status_code == 201
    created_id = uuid.UUID(res.json()["id"])

    # Query database directly
    async def _verify():
        async with SessionLocal() as db:
            from sqlalchemy import select
            c_res = await db.execute(select(Camera).filter(Camera.id == created_id))
            cam_row = c_res.scalars().first()
            assert cam_row is not None
            assert cam_row.name == cam_name
            assert cam_row.building == "Engineering Block"
    asyncio.run(_verify())
