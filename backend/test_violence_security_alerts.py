"""
Test integration between Violence Detection and Security Alerts.
Verifies that:
1. Detected violence events appear in the existing Security Alerts system (GET /api/v1/events/).
2. An alert contains:
   - "Violence Detected" event category
   - Camera information
   - Timestamp
   - Persons identified count
   - Evidence frame & video paths for [View Evidence]
3. AlertDispatcher dispatches automatic notifications with title '⚠ Violence Detected'
   and persons identified count.
4. Non-violence alerts (Fence Jump, Boundary Crossing, Restricted Entry) remain intact.
"""

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

# Setup environment before app imports
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_security_alerts.db"

# Mock out heavy models not needed for alert integration test
from unittest.mock import MagicMock
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from app.main import app
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.api import deps
from sqlalchemy import select
from app.models.user import User
from app.models.incident import Incident, IncidentPerson, Evidence
from app.models.camera import Camera
from app.models.student import Student
from app.models.notification import Notification
from app.services.alert_dispatcher import AlertDispatcher

mock_user = User(
    id=uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890"),
    email="alert_supervisor@campus.edu",
    hashed_password="hashedpassword123",
    full_name="Security Supervisor John",
    is_active=True
)

app.dependency_overrides[deps.get_current_user] = lambda: mock_user

client = TestClient(app)

async def async_setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

def run_async(coro):
    return asyncio.run(coro)

def test_violence_event_in_security_alerts():
    run_async(async_setup_db())

    async def seed_data():
        async with SessionLocal() as db:
            # Create test camera
            cam_uuid = uuid.uuid4()
            cam = Camera(
                id=cam_uuid,
                name="Main Quadrangle Cam 04",
                building="Quadrangle Block",
                floor=1,
                direction="North",
                resolution="1080p",
                location="Campus Quadrangle Zone B",
                status="active"
            )
            db.add(cam)

            # Create two test enrolled students
            stu1 = Student(
                id=uuid.uuid4(),
                name="Alex Mercer",
                university_roll_number=f"CS-{uuid.uuid4().hex[:4].upper()}",
                email=f"alex.{uuid.uuid4().hex[:4]}@campus.edu",
                programme="B.Tech Computer Science",
                department="Computer Science",
                year=4,
                semester=8,
                section="A"
            )
            stu2 = Student(
                id=uuid.uuid4(),
                name="James Heller",
                university_roll_number=f"CS-{uuid.uuid4().hex[:4].upper()}",
                email=f"james.{uuid.uuid4().hex[:4]}@campus.edu",
                programme="B.Tech Computer Science",
                department="Computer Science",
                year=3,
                semester=6,
                section="B"
            )
            db.add(stu1)
            db.add(stu2)
            await db.commit()

            # Create Violence Incident
            incident_id = uuid.uuid4()
            inc = Incident(
                id=incident_id,
                incident_type="Violence",
                confidence=0.92,
                camera_id=cam.id,
                timestamp=datetime.now(timezone.utc),
                explanation="⚠ Violence Detected: Physical Altercation between 2 individuals"
            )
            db.add(inc)
            await db.commit()

            # Associate students
            ip1 = IncidentPerson(
                id=uuid.uuid4(),
                incident_id=inc.id,
                student_id=stu1.id,
                confidence=0.94
            )
            ip2 = IncidentPerson(
                id=uuid.uuid4(),
                incident_id=inc.id,
                student_id=stu2.id,
                confidence=0.91
            )
            db.add(ip1)
            db.add(ip2)

            # Attach evidence
            ev_frame = Evidence(
                id=uuid.uuid4(),
                incident_id=inc.id,
                evidence_type="screenshot",
                file_path="/storage/violence_evidence/frame_quad04.jpg"
            )
            ev_clip = Evidence(
                id=uuid.uuid4(),
                incident_id=inc.id,
                evidence_type="video",
                file_path="/storage/violence_evidence/clip_quad04.mp4"
            )
            db.add(ev_frame)
            db.add(ev_clip)

            # Create a non-violence event (Fence Jump) to ensure no regression on existing alerts
            fence_cam_uuid = uuid.uuid4()
            fence_cam = Camera(
                id=fence_cam_uuid,
                name="Boundary North 01",
                building="Perimeter",
                floor=0,
                direction="East",
                resolution="1080p",
                location="North Perimeter Fence",
                status="active"
            )
            db.add(fence_cam)
            await db.commit()

            fence_inc = Incident(
                id=uuid.uuid4(),
                incident_type="Fence Jump",
                confidence=0.85,
                camera_id=fence_cam.id,
                timestamp=datetime.now(timezone.utc),
                explanation="Perimeter fence crossing detected"
            )
            db.add(fence_inc)
            await db.commit()

            return str(inc.id), str(fence_inc.id), str(cam.id), cam.name

    inc_id, fence_inc_id, cam_id, cam_name = run_async(seed_data())

    # 1. Query Security Alerts endpoint (GET /api/v1/events/)
    response = client.get("/api/v1/events/")
    assert response.status_code == 200, f"GET /events/ failed: {response.text}"
    events = response.json()
    assert isinstance(events, list)

    # Find our violence alert
    violence_alert = next((e for e in events if e["id"] == inc_id), None)
    assert violence_alert is not None, "Violence incident not found in Security Alerts list!"

    # Check required fields
    assert violence_alert["event_type"] == "VIOLENCE"
    assert violence_alert["camera_name"] == "Main Quadrangle Cam 04"
    assert violence_alert["camera_location"] == "Campus Quadrangle Zone B"
    assert violence_alert["timestamp"] is not None
    assert violence_alert["persons_identified_count"] == 2, f"Expected 2 identified persons, got {violence_alert.get('persons_identified_count')}"
    assert violence_alert["evidence_image"] == "/storage/violence_evidence/frame_quad04.jpg"
    assert violence_alert["evidence_video"] == "/storage/violence_evidence/clip_quad04.mp4"
    assert len(violence_alert["students"]) == 2

    # 2. Query Detail endpoint for [View Evidence] (GET /api/v1/events/{id})
    detail_res = client.get(f"/api/v1/events/{inc_id}")
    assert detail_res.status_code == 200, f"GET /events/{inc_id} failed: {detail_res.text}"
    detail = detail_res.json()
    assert detail["event_type"] == "VIOLENCE"
    assert detail["persons_identified_count"] == 2
    assert detail["evidence_video"] == "/storage/violence_evidence/clip_quad04.mp4"
    assert detail["evidence_image"] == "/storage/violence_evidence/frame_quad04.jpg"

    # 3. Verify non-violence alert remains intact
    fence_alert = next((e for e in events if e["id"] == fence_inc_id), None)
    assert fence_alert is not None, "Fence Jump alert was missing or displaced!"
    assert fence_alert["event_type"] == "FENCE_JUMP"
    assert fence_alert["camera_name"] == "Boundary North 01"

    # 4. Verify AlertDispatcher produces the required alert structure
    async def test_dispatcher():
        async with SessionLocal() as db:
            # Ensure a user exists to receive the notification
            user = User(
                id=uuid.uuid4(),
                email="officer_dispatch@campus.edu",
                hashed_password="hashedpassword123",
                full_name="Dispatch Officer Bob",
                is_active=True
            )
            db.add(user)
            await db.commit()

            await AlertDispatcher.dispatch_alert(
                db=db,
                event_type="VIOLENCE",
                camera_name=cam_name,
                persons_identified_count=2
            )

            # Check notification
            notif_res = await db.execute(select(Notification).filter(Notification.user_id == user.id))
            notifications = notif_res.scalars().all()
            assert len(notifications) > 0, "No notifications created by AlertDispatcher!"
            violence_notif = notifications[0]
            assert violence_notif.title == "⚠ Violence Detected"
            assert cam_name in violence_notif.message
            assert "Persons identified: 2" in violence_notif.message
            assert violence_notif.severity == "critical"

    run_async(test_dispatcher())

    print("\n-----------------------------------------------------------")
    print("SUCCESS: Violence Detection correctly integrated into Security Alerts!")
    print("-----------------------------------------------------------")

if __name__ == "__main__":
    test_violence_event_in_security_alerts()
