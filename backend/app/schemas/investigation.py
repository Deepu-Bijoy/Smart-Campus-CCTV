import uuid
from datetime import datetime
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class DashboardResponse(BaseModel):
    total_videos: int
    total_tracks: int
    total_detections: int
    enrolled_students: int
    face_embeddings_count: int
    system_status: str

class TimelineItem(BaseModel):
    id: uuid.UUID
    event_type: str  # "detection", "enrollment", "system"
    timestamp: datetime
    label: str
    description: str
    metadata: Dict[str, Any]

class TimelineResponse(BaseModel):
    items: List[TimelineItem]

class EvidenceResponse(BaseModel):
    incident_id: str
    severity: str
    timestamp: datetime
    summary: str
    media_assets: List[Dict[str, Any]]
    related_tracks: List[uuid.UUID]
