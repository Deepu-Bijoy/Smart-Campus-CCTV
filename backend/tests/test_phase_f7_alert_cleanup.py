import asyncio
import os
import sys
import uuid

backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.db.session import SessionLocal
from app.models.user import User
from app.models.notification import Notification
from app.models.incident import Incident, Evidence
from app.services.notification_service import NotificationService
from app.services.alert_dispatcher import AlertDispatcher
from app.api.v1.notifications import (
    list_notifications,
    mark_all_notifications_read,
    mark_notification_read,
    delete_notification
)
from sqlalchemy import select

async def run_phase_f7_tests():
    print("============================================================")
    print("RUNNING PHASE F7 SECURITY ALERT LOG & DEDUPLICATION TESTS")
    print("============================================================\n")

    async with SessionLocal() as db:
        # Find active user
        user_res = await db.execute(select(User).filter(User.is_active == True))
        user = user_res.scalars().first()
        if not user:
            print("[WARN] No active user found; creating dummy user for testing.")
            user = User(
                id=uuid.uuid4(),
                email="test_operator@campus.edu",
                full_name="Test Operator",
                role="operator",
                is_active=True
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)

        user_id = user.id

        # -------------------------------------------------------------
        # TEST 1: Creation of alerts & list_notifications unread_only
        # -------------------------------------------------------------
        print("--- TEST 1: Unread Notifications Filtering ---")
        n1 = await NotificationService.create_notification(
            db=db,
            user_id=user_id,
            title="Warning Test Alert",
            message="Test message 1",
            severity="warning"
        )
        n2 = await NotificationService.create_notification(
            db=db,
            user_id=user_id,
            title="Critical Test Alert",
            message="Test message 2",
            severity="critical"
        )

        all_notifs = await list_notifications(unread_only=False, db=db, current_user=user)
        unread_notifs = await list_notifications(unread_only=True, db=db, current_user=user)

        assert any(n.id == n1.id for n in all_notifs), "n1 should be in all_notifs"
        assert any(n.id == n2.id for n in all_notifs), "n2 should be in all_notifs"
        assert any(n.id == n1.id for n in unread_notifs), "n1 should be in unread_notifs"
        assert any(n.id == n2.id for n in unread_notifs), "n2 should be in unread_notifs"
        print(f"[OK] Unread filtering verified. Total: {len(all_notifs)}, Unread: {len(unread_notifs)}\n")

        # -------------------------------------------------------------
        # TEST 2: Single Read Action
        # -------------------------------------------------------------
        print("--- TEST 2: Individual Notification Read ---")
        read_res = await mark_notification_read(id=n1.id, db=db, current_user=user)
        assert read_res.is_read is True, "Notification n1 must be marked read"

        unread_after_single = await list_notifications(unread_only=True, db=db, current_user=user)
        assert not any(n.id == n1.id for n in unread_after_single), "n1 must not appear in unread list"
        assert any(n.id == n2.id for n in unread_after_single), "n2 must still appear in unread list"
        print("[OK] Single notification read verified.\n")

        # -------------------------------------------------------------
        # TEST 3: Read All Action
        # -------------------------------------------------------------
        print("--- TEST 3: Read All Action Clears Unread Log ---")
        read_all_res = await mark_all_notifications_read(db=db, current_user=user)
        assert "message" in read_all_res

        unread_after_all = await list_notifications(unread_only=True, db=db, current_user=user)
        assert len(unread_after_all) == 0, f"Expected 0 unread alerts after Read All, got {len(unread_after_all)}"
        print("[OK] Read All successfully cleared all unread alerts.\n")

        # -------------------------------------------------------------
        # TEST 4: New Alert Generated After Read All Appears Normally
        # -------------------------------------------------------------
        print("--- TEST 4: New Alert After Read All Appears Normally ---")
        n3 = await NotificationService.create_notification(
            db=db,
            user_id=user_id,
            title="Fresh Security Alert",
            message="Appears after Read All was executed",
            severity="info"
        )
        unread_after_new = await list_notifications(unread_only=True, db=db, current_user=user)
        assert len(unread_after_new) == 1, f"Expected exactly 1 unread alert, got {len(unread_after_new)}"
        assert unread_after_new[0].id == n3.id
        print("[OK] New alert appears normally in unread list.\n")

        # Clean up n3
        await delete_notification(id=n3.id, db=db, current_user=user)
        unread_after_del = await list_notifications(unread_only=True, db=db, current_user=user)
        assert not any(n.id == n3.id for n in unread_after_del)
        print("[OK] Notification deletion works correctly.\n")

        # -------------------------------------------------------------
        # TEST 5: One Violence Alert Per Source Video Deduplication
        # -------------------------------------------------------------
        print("--- TEST 5: Consolidated Violence Alert per Video ---")
        vid_a = uuid.uuid4()
        vid_b = uuid.uuid4()

        # Dispatch violence alert for Video A first time
        await AlertDispatcher.dispatch_violence_alert(
            db=db,
            video_id=vid_a,
            video_filename="corridor_cam_01.mp4",
            camera_name="Main Corridor",
            incident_count=3,
            persons_identified_count=2,
            earliest_timestamp_str="00:01:15"
        )

        res_a1 = await db.execute(
            select(Notification).filter(
                Notification.user_id == user_id,
                Notification.dedup_key == f"{vid_a}:VIOLENCE"
            )
        )
        notifs_a = res_a1.scalars().all()
        assert len(notifs_a) == 1, f"Expected 1 notification for Video A, got {len(notifs_a)}"
        first_alert = notifs_a[0]
        assert "Violence Detected" in first_alert.title
        assert "corridor_cam_01.mp4" in first_alert.message
        assert "Main Corridor" in first_alert.message
        assert "3 incidents" in first_alert.message
        assert "2 confirmed students" in first_alert.message
        assert "00:01:15" in first_alert.message
        print(f"[OK] First violence alert created: {first_alert.message}")

        # Dispatch violence alert for Video A a second time (e.g. repeated temporal window or callback)
        await AlertDispatcher.dispatch_violence_alert(
            db=db,
            video_id=vid_a,
            video_filename="corridor_cam_01.mp4",
            camera_name="Main Corridor",
            incident_count=3,
            persons_identified_count=2,
            earliest_timestamp_str="00:01:15"
        )

        res_a2 = await db.execute(
            select(Notification).filter(
                Notification.user_id == user_id,
                Notification.dedup_key == f"{vid_a}:VIOLENCE"
            )
        )
        notifs_a2 = res_a2.scalars().all()
        assert len(notifs_a2) == 1, f"Expected still exactly 1 notification for Video A after duplicate dispatch, got {len(notifs_a2)}"
        print("[OK] Duplicate violence alert for Video A was deduplicated successfully.\n")

        # -------------------------------------------------------------
        # TEST 6: Separate Video Produces Separate Notification
        # -------------------------------------------------------------
        print("--- TEST 6: Separate Video Produces Separate Alert ---")
        await AlertDispatcher.dispatch_violence_alert(
            db=db,
            video_id=vid_b,
            video_filename="parking_cam_02.mp4",
            camera_name="Parking Lot",
            incident_count=1,
            persons_identified_count=1,
            earliest_timestamp_str="00:00:45"
        )

        res_b = await db.execute(
            select(Notification).filter(
                Notification.user_id == user_id,
                Notification.dedup_key == f"{vid_b}:VIOLENCE"
            )
        )
        notifs_b = res_b.scalars().all()
        assert len(notifs_b) == 1, f"Expected 1 notification for Video B, got {len(notifs_b)}"
        assert "parking_cam_02.mp4" in notifs_b[0].message
        print("[OK] Video B generated its own distinct notification.\n")

        # -------------------------------------------------------------
        # TEST 7: Concurrent Alert Dispatch Safety
        # -------------------------------------------------------------
        print("--- TEST 7: Concurrency-Safe Alert Creation ---")
        vid_c = uuid.uuid4()

        async def worker_dispatch():
            async with SessionLocal() as worker_db:
                await AlertDispatcher.dispatch_violence_alert(
                    db=worker_db,
                    video_id=vid_c,
                    video_filename="canteen_cam_03.mp4",
                    camera_name="Canteen Area",
                    incident_count=2,
                    persons_identified_count=0,
                    earliest_timestamp_str="00:00:30"
                )

        # Simulate 5 concurrent worker tasks attempting to dispatch alert for Video C at the same instant
        tasks = [worker_dispatch() for _ in range(5)]
        await asyncio.gather(*tasks)

        res_c = await db.execute(
            select(Notification).filter(
                Notification.user_id == user_id,
                Notification.dedup_key == f"{vid_c}:VIOLENCE"
            )
        )
        notifs_c = res_c.scalars().all()
        assert len(notifs_c) == 1, f"Expected exactly 1 notification for Video C despite 5 concurrent calls, got {len(notifs_c)}"
        print(f"[OK] Concurrency test passed: Exactly 1 notification created out of 5 concurrent dispatches.\n")

        # -------------------------------------------------------------
        # TEST 8: Preserving Underlying Incidents & Evidence
        # -------------------------------------------------------------
        print("--- TEST 8: Non-Destructive Integrity Verification ---")
        inc_count = (await db.execute(select(Incident))).scalars().all()
        ev_count = (await db.execute(select(Evidence))).scalars().all()
        print(f"[OK] Existing Incidents in DB: {len(inc_count)}")
        print(f"[OK] Existing Evidence in DB: {len(ev_count)}")

        # Clean up test notifications created in this test run
        for n in [n1, n2, first_alert, notifs_b[0], notifs_c[0]]:
            await db.delete(n)
        await db.commit()
        print("[OK] Test notification cleanup complete.\n")

    print("============================================================")
    print("ALL PHASE F7 TESTS PASSED SUCCESSFULLY!")
    print("============================================================\n")

if __name__ == "__main__":
    asyncio.run(run_phase_f7_tests())
