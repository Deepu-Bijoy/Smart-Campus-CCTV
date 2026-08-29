import sys
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Mock out heavy deep learning and client packages before app main loads
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['qdrant_client'] = MagicMock()
sys.modules['qdrant_client.http'] = MagicMock()
sys.modules['transformers'] = MagicMock()

# Add backend to sys.path using direct absolute path
backend_path = r"c:\Users\Asus\OneDrive\Desktop\AI-Powered Smart CCTV Investigation System\backend"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from fastapi import status
from app.main import app
from app.api import deps
from app.models.user import User
from app.models.camera import Camera, VirtualZone

mock_user = User(
    id=uuid.UUID("d3b7a123-4567-89ab-cdef-0123456789ab"),
    email="operator@smartcampus.com",
    hashed_password="hashedpassword123",
    full_name="Lead Security Operator",
    is_active=True
)

app.dependency_overrides[deps.get_current_user] = lambda: mock_user

client = TestClient(app)

class MockScalarResult:
    def __init__(self, value):
        self._value = value
    def first(self):
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value
    def all(self):
        return [self._value] if not isinstance(self._value, list) else self._value

class MockSQLResult:
    def __init__(self, value):
        self._value = value
    def scalars(self):
        return MockScalarResult(self._value)
    def all(self):
        return [self._value] if not isinstance(self._value, list) else self._value

def test_camera_crud_endpoints():
    camera_id = uuid.uuid4()
    zone_id = uuid.uuid4()
    
    mock_camera = Camera(
        id=camera_id,
        name="Camera-NorthGate",
        group_id=None,
        building="Admin Block",
        floor=1,
        location="North Entrance Gate",
        latitude=12.9716,
        longitude=77.5946,
        direction="North",
        field_of_view=90.0,
        resolution="1920x1080",
        status="active",
        snapshot_path="/storage/snapshots/camera_north_gate.jpg",
        created_at=datetime.now(timezone.utc),
        zones=[],
        calibrations=[]
    )
    
    mock_zone = VirtualZone(
        id=zone_id,
        camera_id=camera_id,
        name="North Gate Fence",
        zone_type="Fence",
        geometry_type="polygon",
        coordinates="[[100,200],[300,400],[500,200]]",
        created_at=datetime.now(timezone.utc)
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt).lower()
        if "virtualzone" in stmt_str or "virtual_zone" in stmt_str:
            return MockSQLResult([mock_zone])
        elif "camera" in stmt_str:
            return MockSQLResult([mock_camera])
        return MockSQLResult([])

    async def mock_commit():
        pass

    async def mock_refresh(obj):
        pass

    async def mock_delete(obj):
        pass

    mock_db = MagicMock()
    mock_db.execute = mock_execute
    mock_db.commit = mock_commit
    mock_db.refresh = mock_refresh
    mock_db.delete = mock_delete
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    print("Checking POST /cameras...")
    payload = {
        "name": "Camera-NorthGate",
        "building": "Admin Block",
        "floor": 1,
        "location": "North Entrance Gate",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "direction": "North",
        "field_of_view": 90.0,
        "resolution": "1920x1080",
        "status": "active",
        "snapshot_path": "/storage/snapshots/camera_north_gate.jpg"
    }
    first_call = True
    async def mock_execute_create(stmt):
        nonlocal first_call
        if first_call:
            first_call = False
            return MockSQLResult([])
        return MockSQLResult([mock_camera])
    mock_db.execute = mock_execute_create
    response = client.post("/api/v1/cameras/", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["name"] == "Camera-NorthGate"

    mock_db.execute = mock_execute

    print("Checking GET /cameras...")
    response = client.get("/api/v1/cameras/")
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1

    print("Checking GET /cameras/{id}...")
    response = client.get(f"/api/v1/cameras/{camera_id}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["building"] == "Admin Block"

    print("Checking PUT /cameras/{id}...")
    update_payload = {"location": "North Entrance Gate main"}
    response = client.put(f"/api/v1/cameras/{camera_id}", json=update_payload)
    assert response.status_code == status.HTTP_200_OK

    print("Checking POST /cameras/{id}/zones...")
    zone_payload = {
        "name": "North Gate Fence",
        "zone_type": "Fence",
        "geometry_type": "polygon",
        "coordinates": "[[100,200],[300,400],[500,200]]"
    }
    response = client.post(f"/api/v1/cameras/{camera_id}/zones", json=zone_payload)
    assert response.status_code == status.HTTP_201_CREATED

    print("Checking DELETE /cameras/{id}...")
    response = client.delete(f"/api/v1/cameras/{camera_id}")
    assert response.status_code == status.HTTP_200_OK

    print("All Camera Management API endpoints verified successfully!")

if __name__ == "__main__":
    test_camera_crud_endpoints()
