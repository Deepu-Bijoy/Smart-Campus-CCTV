import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

class VideoBase(BaseModel):
    title: Optional[str] = None

class VideoCreate(VideoBase):
    pass

class VideoUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    codec: Optional[str] = None
    file_size: Optional[int] = None

class VideoResponse(BaseModel):
    id: uuid.UUID
    title: Optional[str] = None
    filename: str
    original_filename: str
    file_path: str
    status: str
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    codec: Optional[str] = None
    file_size: Optional[int] = None
    
    # Progress tracking fields
    current_stage: Optional[str] = None
    progress_percentage: int
    processing_started_at: Optional[datetime] = None
    processing_finished_at: Optional[datetime] = None
    error_message: Optional[str] = None

    camera_id: Optional[uuid.UUID] = None
    uploaded_by: uuid.UUID
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class VideoStatusResponse(BaseModel):
    video_id: uuid.UUID
    status: str
    stage: Optional[str] = None
    progress: int

    model_config = ConfigDict(from_attributes=True)
