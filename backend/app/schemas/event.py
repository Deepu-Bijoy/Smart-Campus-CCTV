import uuid
from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional

class EventTrackResponse(BaseModel):
    id: uuid.UUID
    event_id: uuid.UUID
    track_id: uuid.UUID

    class Config:
        from_attributes = True

class EventResponse(BaseModel):
    id: uuid.UUID
    event_type: str
    camera_id: Optional[uuid.UUID] = None
    camera_name: Optional[str] = None
    camera_location: Optional[str] = None
    video_id: Optional[uuid.UUID] = None
    timestamp: datetime
    zone_id: Optional[uuid.UUID] = None
    student_id: Optional[uuid.UUID] = None
    student_name: Optional[str] = None
    student_roll: Optional[str] = None
    students: List[dict] = []
    confidence: str
    confidence_score: Optional[float] = None
    explanation: Optional[str] = None
    evidence_image: Optional[str] = None
    evidence_video: Optional[str] = None
    tracks: List[EventTrackResponse] = []
    persons_identified_count: Optional[int] = None

    class Config:
        from_attributes = True
