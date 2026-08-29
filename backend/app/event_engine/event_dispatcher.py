import uuid
import logging
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.event import Event, EventTrack
from app.models.recognition import StudentRecognitionEvent

logger = logging.getLogger(__name__)

class EventDispatcher:
    @staticmethod
    async def dispatch_event(
        db: AsyncSession,
        event_type: str,
        camera_id: uuid.UUID,
        video_id: uuid.UUID,
        zone_id: uuid.UUID,
        track_id: uuid.UUID,
        timestamp: datetime,
        confidence: str = "high"
    ) -> Event:
        stmt = (
            select(StudentRecognitionEvent)
            .filter(StudentRecognitionEvent.track_id == track_id)
            .order_by(StudentRecognitionEvent.similarity_score.desc())
        )
        rec_res = await db.execute(stmt)
        rec_event = rec_res.scalars().first()
        
        student_id = rec_event.student_id if rec_event else None
        
        event_id = uuid.uuid4()
        event_obj = Event(
            id=event_id,
            event_type=event_type,
            camera_id=camera_id,
            video_id=video_id,
            zone_id=zone_id,
            student_id=student_id,
            timestamp=timestamp,
            confidence=confidence
        )
        db.add(event_obj)
        
        track_link = EventTrack(
            id=uuid.uuid4(),
            event_id=event_id,
            track_id=track_id
        )
        db.add(track_link)
        
        await db.commit()
        await db.refresh(event_obj)
        
        logger.info(f"Dispatched Event {event_type} on camera {camera_id} for track {track_id}")
        return event_obj
