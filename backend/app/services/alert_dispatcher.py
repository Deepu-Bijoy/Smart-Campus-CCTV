import uuid
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

class AlertDispatcher:
    @staticmethod
    async def dispatch_violence_alert(
        db: AsyncSession,
        video_id: uuid.UUID,
        video_filename: str,
        camera_name: str,
        incident_count: int = 1,
        persons_identified_count: int = 0,
        earliest_timestamp_str: str = "00:00:00",
        run_id: Optional[str] = None
    ):
        """
        Dispatches one consolidated violence alert per source video and processing run.
        Uses dedup_key = f"{video_id}:VIOLENCE:{run_id}" when run_id is supplied,
        or f"{video_id}:VIOLENCE" for backward compatibility.
        """
        user_stmt = select(User.id).filter(User.is_active == True)
        res = await db.execute(user_stmt)
        user_ids = res.scalars().all()
        if not user_ids:
            return

        title = "⚠ Violence Detected"
        inc_text = f"{incident_count} incident{'s' if incident_count != 1 else ''}"
        student_text = f"{persons_identified_count} confirmed student{'s' if persons_identified_count != 1 else ''}"
        
        # Format informative, consolidated alert message meeting all requirement specs
        message = (
            f"Physical altercation detected on camera {camera_name} ({video_filename}) "
            f"at {earliest_timestamp_str}. Incidents: {inc_text}, Students: {student_text}."
        )

        dedup_key = f"{video_id}:VIOLENCE:{run_id}" if run_id else f"{video_id}:VIOLENCE"

        for uid in user_ids:
            await NotificationService.create_notification(
                db=db,
                user_id=uid,
                title=title,
                message=message,
                severity="critical",
                dedup_key=dedup_key
            )

    @staticmethod
    async def dispatch_alert(
        db: AsyncSession,
        event_type: str,
        camera_name: str,
        student_name: str = None,
        confidence: str = "high",
        persons_identified_count: int = 0,
        video_id: Optional[uuid.UUID] = None,
        video_filename: Optional[str] = None,
        timestamp_str: Optional[str] = None,
        incident_count: int = 1,
        run_id: Optional[str] = None
    ):
        if event_type in ["VIOLENCE", "FIGHT"] and video_id:
            await AlertDispatcher.dispatch_violence_alert(
                db=db,
                video_id=video_id,
                video_filename=video_filename or "CCTV Video",
                camera_name=camera_name,
                incident_count=incident_count,
                persons_identified_count=persons_identified_count,
                earliest_timestamp_str=timestamp_str or "00:00:00",
                run_id=run_id
            )
            return

        user_stmt = select(User.id).filter(User.is_active == True)
        res = await db.execute(user_stmt)
        user_ids = res.scalars().all()
        if not user_ids:
            return
        
        severity = "info"
        if event_type in ["VIOLENCE", "FIGHT"]:
            title = "⚠ Violence Detected"
            message = f"Physical altercation detected on camera {camera_name}. Persons identified: {persons_identified_count}."
            severity = "critical"
        elif event_type == "FENCE_JUMP":
            title = "Fence Intrusion Alert"
            message = f"Subject jumped boundary fence at {camera_name}."
            severity = "critical"
        elif event_type == "RESTRICTED_ENTRY":
            title = "Restricted Area Entry"
            message = f"Subject entered restricted boundary zone at {camera_name}."
            severity = "warning"
        elif student_name:
            title = "Student Identified Match"
            message = f"Student {student_name} matched on camera {camera_name}."
            severity = "info"
        else:
            title = f"Alert Triggered: {event_type}"
            message = f"Event recorded on camera {camera_name}."
            
        if confidence == "high" and severity != "critical":
            severity = "warning"

        dedup_key = f"{video_id}:{event_type}" if video_id else None

        for uid in user_ids:
            await NotificationService.create_notification(
                db=db,
                user_id=uid,
                title=title,
                message=message,
                severity=severity,
                dedup_key=dedup_key
            )
