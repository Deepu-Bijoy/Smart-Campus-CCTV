import os
import sys
import uuid
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

# Mock out heavy ML modules not needed for API route validation
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['insightface'] = MagicMock()
sys.modules['insightface.app'] = MagicMock()

backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from sqlalchemy import select, or_, cast, String
from app.main import app
from app.api import deps
from app.core import security
from app.db.session import SessionLocal
from app.models.user import User
from app.models.camera import Camera, VirtualZone

client = TestClient(app)

async def _get_admin_headers():
    async with SessionLocal() as db:
        res = await db.execute(select(User).filter(User.is_active == True, User.role == "admin"))
        user = res.scalars().first()
        if not user:
            res = await db.execute(select(User).filter(User.is_active == True))
            user = res.scalars().first()
        assert user is not None, "At least one active user must exist"
        token = security.create_access_token(user.id)
        return {"Authorization": f"Bearer {token}"}

async def run_f12_regression_tests():
    print("=====================================================================")
    print("PHASE F12: VIRTUAL INTRUSION ZONE DELETION REGRESSION TEST SUITE")
    print("=====================================================================")

    headers = await _get_admin_headers()
    
    # Setup test cameras A and B
    cam_a_id = uuid.uuid4()
    cam_b_id = uuid.uuid4()
    
    async with SessionLocal() as db:
        cam_a = Camera(
            id=cam_a_id,
            name="F12-Test-Camera-A",
            building="Building Alpha",
            floor=1,
            location="Perimeter North",
            direction="North",
            resolution="1080p",
            status="active",
            created_at=datetime.now(timezone.utc)
        )
        cam_b = Camera(
            id=cam_b_id,
            name="F12-Test-Camera-B",
            building="Building Beta",
            floor=2,
            location="Perimeter South",
            direction="South",
            resolution="1080p",
            status="active",
            created_at=datetime.now(timezone.utc)
        )
        db.add_all([cam_a, cam_b])
        await db.commit()

    try:
        # -------------------------------------------------------------------
        # Test 1: Creating a zone and retrieving it returns its persisted ID
        # -------------------------------------------------------------------
        print("[TEST 1] Creating a zone on Camera A and retrieving persisted ID...")
        create_payload = {
            "name": "Zone-Primary-Alpha",
            "zone_type": "Restricted Area",
            "geometry_type": "polygon",
            "coordinates": json.dumps([[10, 10], [50, 10], [50, 50], [10, 50]])
        }
        res = client.post(f"/api/v1/cameras/{cam_a_id}/zones", json=create_payload, headers=headers)
        assert res.status_code == 201, f"Expected 201 Created, got {res.status_code}: {res.text}"
        zone_data = res.json()
        zone_1_id = zone_data["id"]
        assert uuid.UUID(zone_1_id), "Returned ID must be a valid UUID string"
        print(f"  -> Zone created successfully with persisted ID: {zone_1_id}")

        # Retrieve Camera A details
        get_res = client.get(f"/api/v1/cameras/{cam_a_id}", headers=headers)
        assert get_res.status_code == 200
        cam_zones = get_res.json().get("zones", [])
        matched_zone = next((z for z in cam_zones if z["id"] == zone_1_id), None)
        assert matched_zone is not None, "Created zone must appear in Camera GET response"
        assert matched_zone["name"] == "Zone-Primary-Alpha"
        assert matched_zone["zone_type"] == "Restricted Area"
        print("  -> Verified: GET camera returns the persisted zone ID and attributes.")

        # Also create a second unrelated zone on Camera A to test isolation
        unrelated_payload = {
            "name": "Zone-Unrelated-Beta",
            "zone_type": "Fence",
            "geometry_type": "line",
            "coordinates": json.dumps([[100, 100], [200, 200]])
        }
        res_unrelated = client.post(f"/api/v1/cameras/{cam_a_id}/zones", json=unrelated_payload, headers=headers)
        assert res_unrelated.status_code == 201
        zone_unrelated_id = res_unrelated.json()["id"]
        print(f"  -> Unrelated zone created on Camera A: {zone_unrelated_id}")

        # -------------------------------------------------------------------
        # Test 2: Deleting a nonexistent zone returns 404
        # -------------------------------------------------------------------
        print("[TEST 2] Deleting nonexistent zone returns 404...")
        fake_zone_id = uuid.uuid4()
        del_nonexistent = client.delete(f"/api/v1/cameras/{cam_a_id}/zones/{fake_zone_id}", headers=headers)
        assert del_nonexistent.status_code == 404, f"Expected 404, got {del_nonexistent.status_code}"
        assert del_nonexistent.json()["detail"] == "Zone not found."
        print("  -> Verified: Nonexistent zone returns HTTP 404 Not Found.")

        # -------------------------------------------------------------------
        # Test 3: Zone belonging to another camera cannot be deleted through wrong camera ID
        # -------------------------------------------------------------------
        print("[TEST 3] Deleting zone through wrong camera ID fails with 400 Bad Request...")
        del_wrong_cam = client.delete(f"/api/v1/cameras/{cam_b_id}/zones/{zone_1_id}", headers=headers)
        assert del_wrong_cam.status_code == 400, f"Expected 400 Bad Request, got {del_wrong_cam.status_code}"
        assert "does not belong" in del_wrong_cam.json()["detail"]
        print("  -> Verified: Cross-camera deletion blocked. Detail:", del_wrong_cam.json()["detail"])

        # Verify zone is still present on Camera A
        get_after_wrong = client.get(f"/api/v1/cameras/{cam_a_id}", headers=headers)
        current_zone_ids = [z["id"] for z in get_after_wrong.json().get("zones", [])]
        assert zone_1_id in current_zone_ids, "Zone must NOT be deleted by failed cross-camera request"
        print("  -> Verified: Zone was retained and unaffected on Camera A.")

        # -------------------------------------------------------------------
        # Test 4: Failed deletion does not corrupt unrelated zones
        # -------------------------------------------------------------------
        print("[TEST 4] Verifying failed operations did not corrupt unrelated zones...")
        assert zone_unrelated_id in current_zone_ids, "Unrelated zone must remain intact"
        print("  -> Verified: Unrelated zone remains completely intact.")

        # -------------------------------------------------------------------
        # Test 5: Deleting an existing zone from its correct camera succeeds
        # -------------------------------------------------------------------
        print("[TEST 5] Deleting existing zone from its correct camera succeeds...")
        del_correct = client.delete(f"/api/v1/cameras/{cam_a_id}/zones/{zone_1_id}", headers=headers)
        assert del_correct.status_code == 200, f"Expected 200 OK, got {del_correct.status_code}: {del_correct.text}"
        assert del_correct.json() == {"message": "Zone successfully deleted."}
        print("  -> Verified: Received documented success response.")

        # -------------------------------------------------------------------
        # Test 6: The deleted zone no longer appears in subsequent GET/list response
        # -------------------------------------------------------------------
        print("[TEST 6] Verifying deleted zone no longer appears in GET response...")
        get_after_del = client.get(f"/api/v1/cameras/{cam_a_id}", headers=headers)
        remaining_zone_ids = [z["id"] for z in get_after_del.json().get("zones", [])]
        assert zone_1_id not in remaining_zone_ids, "Deleted zone must not appear in camera response"
        assert zone_unrelated_id in remaining_zone_ids, "Unrelated zone must still be present"
        print("  -> Verified: Deleted zone removed from authoritative GET response, unrelated zone preserved.")

        # -------------------------------------------------------------------
        # Test 7: Verify legacy 32-char hex formatted zone deletion works seamlessly
        # -------------------------------------------------------------------
        print("[TEST 7] Testing legacy 32-char hex UUID zone deletion...")
        legacy_raw_id = uuid.uuid4().hex  # 32 characters, no hyphens
        async with SessionLocal() as db:
            legacy_zone = VirtualZone(
                id=legacy_raw_id,
                camera_id=cam_a_id,
                name="Legacy-32Hex-Zone",
                zone_type="Restricted Area",
                geometry_type="polygon",
                coordinates="[[0,0],[10,10]]",
                created_at=datetime.now(timezone.utc)
            )
            db.add(legacy_zone)
            await db.commit()

        # Try deleting using standard canonical UUID formatted request
        legacy_canon_uuid = str(uuid.UUID(legacy_raw_id))
        del_legacy = client.delete(f"/api/v1/cameras/{cam_a_id}/zones/{legacy_canon_uuid}", headers=headers)
        assert del_legacy.status_code == 200, f"Expected 200, got {del_legacy.status_code}: {del_legacy.text}"
        print("  -> Verified: Legacy 32-char hex record successfully found and deleted using 36-char canonical path parameter.")

        # -------------------------------------------------------------------
        # Test 8: Repeating deletion on now-deleted zone returns deterministic 404
        # -------------------------------------------------------------------
        print("[TEST 8] Verifying repeated DELETE on deleted zone returns deterministic 404 (no retry)...")
        repeat_del = client.delete(f"/api/v1/cameras/{cam_a_id}/zones/{zone_1_id}", headers=headers)
        assert repeat_del.status_code == 404
        print("  -> Verified: Repeat delete returns single 404 without corruption.")

    finally:
        # Cleanup test cameras and their zones
        print("\nCleaning up test cameras and zones...")
        async with SessionLocal() as db:
            # Delete test zones
            await db.execute(select(VirtualZone).filter(VirtualZone.camera_id.in_([cam_a_id, cam_b_id])))
            # Delete test cameras
            cam_del_stmt = select(Camera).filter(Camera.id.in_([cam_a_id, cam_b_id]))
            res = await db.execute(cam_del_stmt)
            for c in res.scalars().all():
                await db.delete(c)
            await db.commit()
        print("Cleanup completed.")

    print("\n=====================================================================")
    print("[SUCCESS] ALL PHASE F12 REGRESSION TESTS PASSED PERFECTLY!")
    print("=====================================================================")

if __name__ == "__main__":
    import asyncio
    asyncio.run(run_f12_regression_tests())
