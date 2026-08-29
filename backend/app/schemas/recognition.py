import uuid
from datetime import datetime
from pydantic import BaseModel
from typing import List, Optional

class StudentAppearanceResponse(BaseModel):
    event_id: uuid.UUID
    track_id: uuid.UUID
    video_id: uuid.UUID
    timestamp: datetime
    similarity_score: float
    confidence: str
    camera_id: Optional[str] = None

class TrackStudentResponse(BaseModel):
    track_id: uuid.UUID
    student_id: Optional[uuid.UUID] = None
    student_name: Optional[str] = None
    similarity_score: Optional[float] = None
    confidence: Optional[str] = None

class VideoStudentsResponse(BaseModel):
    student_id: uuid.UUID
    student_name: str
    roll_number: str
    appearances_count: int
    max_similarity: float
    confidence: str
