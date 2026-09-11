import uuid
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)

class AlertDispatcher:
    @staticmethod
    async def dispatch_alert(
        db: AsyncSession,
        event_type: str,
        camera_name: str,
        student_name: str = None,
        confidence: str = "high",
        persons_identified_count: int = 0
    ):
        user_stmt = select(User).filter(User.is_active == True)
        res = await db.execute(user_stmt)
        users = res.scalars().all()
        
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

        for user in users:
            await NotificationService.create_notification(
                db=db,
                user_id=user.id,
                title=title,
                message=message,
                severity=severity
            )
