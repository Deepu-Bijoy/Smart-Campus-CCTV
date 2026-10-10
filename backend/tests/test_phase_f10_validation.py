import asyncio
import os
import sys
import uuid
import sqlite3
from datetime import datetime

backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.db.session import SessionLocal
from app.models.user import User
from app.models.notification import Notification
from app.models.incident import Incident, Evidence
from app.models.video import Video
from app.services.notification_service import NotificationService, ws_manager
from app.services.alert_dispatcher import AlertDispatcher
from app.api.v1.notifications import (
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read
)
from sqlalchemy import select

async def run_phase_f10_validation():
    print("=" * 70)
    print("PHASE F10 COMPREHENSIVE VALIDATION SUITE")
    print("=" * 70)

    # 1. Database Integrity and Foreign Key Checks
    print("\n--- CHECK 1: SQLite Integrity & Foreign Key Checks ---")
    db_path = os.path.join(backend_path, "storage", "cctv.db")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA integrity_check;")
    integrity = cursor.fetchall()
    assert integrity == [("ok",)], f"Integrity check failed: {integrity}"
    print("[PASS] PRAGMA integrity_check: ok")

    cursor.execute("PRAGMA foreign_key_check;")
    fk_check = cursor.fetchall()
    assert len(fk_check) == 0, f"Foreign key violations found: {fk_check}"
    print("[PASS] PRAGMA foreign_key_check: 0 violations")
    conn.close()

    async with SessionLocal() as db:
        user_res = await db.execute(select(User).filter(User.is_active == True))
        user = user_res.scalars().first()
        assert user is not None, "Active user must exist"
        user_id = user.id

        # 2. First-Detection Alert & Idempotency Key Scoped to Source Video and Processing Run
        print("\n--- CHECK 2 & 3 & 4: Single Alert per Run & Multi-Run Alert Lifecycle ---")
        vid_1 = uuid.uuid4()
        vid_2 = uuid.uuid4()
        run_1 = "20261010120000"
        run_2 = "20261010130000"

        # Run 1 - Window 1 (first detection)
        await AlertDispatcher.dispatch_violence_alert(
            db=db,
            video_id=vid_1,
            video_filename="gate_cam_run1.mp4",
            camera_name="Main Gate",
            incident_count=1,
            persons_identified_count=1,
            earliest_timestamp_str="00:00:10",
            run_id=run_1
        )

        # Run 1 - Window 2 (subsequent window/frame - should be deduplicated!)
        await AlertDispatcher.dispatch_violence_alert(
            db=db,
            video_id=vid_1,
            video_filename="gate_cam_run1.mp4",
            camera_name="Main Gate",
            incident_count=2,
            persons_identified_count=2,
            earliest_timestamp_str="00:00:10",
            run_id=run_1
        )

        res_run1 = await db.execute(
            select(Notification).filter(
                Notification.user_id == user_id,
                Notification.dedup_key == f"{vid_1}:VIOLENCE:{run_1}"
            )
        )
        notifs_run1 = res_run1.scalars().all()
        assert len(notifs_run1) == 1, f"Expected exactly 1 notification for Run 1, got {len(notifs_run1)}"
        print("[PASS] Exactly 1 alert generated for first detection in Run 1; subsequent windows suppressed.")

        # Run 2 - Video 1 reprocessed in a fresh processing run
        await AlertDispatcher.dispatch_violence_alert(
            db=db,
            video_id=vid_1,
            video_filename="gate_cam_run1.mp4",
            camera_name="Main Gate",
            incident_count=1,
            persons_identified_count=1,
            earliest_timestamp_str="00:00:10",
            run_id=run_2
        )

        res_run2 = await db.execute(
            select(Notification).filter(
                Notification.user_id == user_id,
                Notification.dedup_key == f"{vid_1}:VIOLENCE:{run_2}"
            )
        )
        notifs_run2 = res_run2.scalars().all()
        assert len(notifs_run2) == 1, f"Expected 1 notification for Run 2, got {len(notifs_run2)}"
        print("[PASS] Reprocessed video with fresh run_id correctly generates legitimate new alert for run 2.")

        # Different video produces its own alert
        await AlertDispatcher.dispatch_violence_alert(
            db=db,
            video_id=vid_2,
            video_filename="library_cam_run1.mp4",
            camera_name="Library",
            incident_count=1,
            persons_identified_count=0,
            earliest_timestamp_str="00:01:45",
            run_id=run_1
        )

        res_vid2 = await db.execute(
            select(Notification).filter(
                Notification.user_id == user_id,
                Notification.dedup_key == f"{vid_2}:VIOLENCE:{run_1}"
            )
        )
        notifs_vid2 = res_vid2.scalars().all()
        assert len(notifs_vid2) == 1, f"Expected 1 notification for Video 2, got {len(notifs_vid2)}"
        print("[PASS] Different source video generates its own distinct alert.")

        # 5. Targeted WebSocket Delivery (No 12x Broadcast Amplification)
        print("\n--- CHECK 5: Targeted WebSocket User Routing ---")
        class MockWebSocket:
            def __init__(self, name):
                self.name = name
                self.received = []

            async def accept(self):
                pass

            async def send_json(self, data):
                self.received.append(data)

            async def send_text(self, text):
                self.received.append(text)

        mock_ws_user = MockWebSocket("user_ws")
        mock_ws_other = MockWebSocket("other_ws")
        other_user_id = uuid.uuid4()

        await ws_manager.connect(mock_ws_user, user_id=str(user_id))
        await ws_manager.connect(mock_ws_other, user_id=str(other_user_id))

        # Create notification for user_id
        notif_targeted = await NotificationService.create_notification(
            db=db,
            user_id=user_id,
            title="Targeted Test Alert",
            message="Testing user-specific dispatch",
            severity="info"
        )

        assert len(mock_ws_user.received) == 1, f"User should receive exactly 1 message, got {len(mock_ws_user.received)}"
        assert len(mock_ws_other.received) == 0, f"Other user should receive 0 messages, got {len(mock_ws_other.received)}"
        print("[PASS] Notification delivered strictly to target user; no global broadcast amplification.")

        ws_manager.disconnect(mock_ws_user, user_id=str(user_id))
        ws_manager.disconnect(mock_ws_other, user_id=str(other_user_id))

        # 6. Read All Action and Persistence
        print("\n--- CHECK 6: Read All and Unread Filtering ---")
        unread_before = await list_notifications(unread_only=True, db=db, current_user=user)
        print(f"[INFO] Unread count before Read All: {len(unread_before)}")
        await mark_all_notifications_read(db=db, current_user=user)
        unread_after = await list_notifications(unread_only=True, db=db, current_user=user)
        assert len(unread_after) == 0, f"Expected 0 unread alerts after Read All, got {len(unread_after)}"
        print("[PASS] Read All successfully cleared unread list.")

        # 7. Non-Destructive Integrity: Incidents, Videos, Evidence
        print("\n--- CHECK 7: Data Integrity & Non-Destructive Invariance ---")
        incidents = (await db.execute(select(Incident))).scalars().all()
        evidence_records = (await db.execute(select(Evidence))).scalars().all()
        videos = (await db.execute(select(Video))).scalars().all()
        assert len(incidents) >= 4, f"Incidents should be preserved, count={len(incidents)}"
        assert len(evidence_records) >= 8, f"Evidence should be preserved, count={len(evidence_records)}"
        assert len(videos) >= 3, f"Videos should be preserved, count={len(videos)}"
        print(f"[PASS] Preserved counts: {len(videos)} videos, {len(incidents)} incidents, {len(evidence_records)} evidence items.")

        # Cleanup test notifications created during this test
        for n in [notifs_run1[0], notifs_run2[0], notifs_vid2[0], notif_targeted]:
            await db.delete(n)
        await db.commit()
        print("[PASS] Test notifications safely cleaned up.")

    # 8. Check Student Directory UI Code for absence of "Active" badge
    print("\n--- CHECK 8: Frontend Student Directory Badge Check ---")
    frontend_card_path = os.path.join(backend_path, "..", "frontend", "src", "components", "StudentCard.tsx")
    with open(frontend_card_path, "r", encoding="utf-8") as f:
        card_content = f.read()

    assert "student.status" not in card_content, "student.status must not be rendered in StudentCard"
    assert "Active" not in card_content, "'Active' text must not be rendered in StudentCard"
    print("[PASS] StudentCard.tsx contains no 'Active' badge or student.status label.")

    frontend_students_path = os.path.join(backend_path, "..", "frontend", "src", "pages", "Students.tsx")
    with open(frontend_students_path, "r", encoding="utf-8") as f:
        students_content = f.read()
    assert "Active" not in students_content, "'Active' text must not be rendered in Students.tsx"
    print("[PASS] Students.tsx contains no 'Active' label.")

    print("\n" + "=" * 70)
    print("ALL PHASE F10 VALIDATION CHECKS PASSED WITH ZERO ERRORS!")
    print("=" * 70)

if __name__ == "__main__":
    asyncio.run(run_phase_f10_validation())
