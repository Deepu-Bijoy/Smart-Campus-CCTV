import uuid
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, ConfigDict

class DetectionBase(BaseModel):
    frame_number: int
    timestamp_seconds: float
    bounding_box: List[float]
    confidence: float

class DetectionCreate(DetectionBase):
    pass

class DetectionResponse(DetectionBase):
    id: uuid.UUID
    track_id: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class TrackBase(BaseModel):
    object_class: str
    tracker_id: int
    start_time: float
    end_time: float
    key_frame_path: Optional[str] = None

class TrackCreate(TrackBase):
    video_id: uuid.UUID

class TrackResponse(TrackBase):
    id: uuid.UUID
    video_id: uuid.UUID
    created_at: datetime
    detections: List[DetectionResponse] = []

    model_config = ConfigDict(from_attributes=True)
