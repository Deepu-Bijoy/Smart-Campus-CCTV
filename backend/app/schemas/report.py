import uuid
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class ReportCreate(BaseModel):
    title: str
    incident_type: str
    incident_id: Optional[uuid.UUID] = None
    student_id: Optional[uuid.UUID] = None
    data: dict

    model_config = {"extra": "ignore"}

class ReportResponse(BaseModel):
    id: uuid.UUID
    title: str
    incident_type: str
    incident_id: Optional[uuid.UUID] = None
    student_id: Optional[uuid.UUID] = None
    created_at: datetime
    data: dict

    class Config:
        from_attributes = True
