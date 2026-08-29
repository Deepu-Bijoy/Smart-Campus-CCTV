import uuid
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class ReportCreate(BaseModel):
    title: str
    incident_type: str
    student_id: Optional[uuid.UUID] = None
    data: dict

class ReportResponse(BaseModel):
    id: uuid.UUID
    title: str
    incident_type: str
    student_id: Optional[uuid.UUID] = None
    created_at: datetime
    data: dict

    class Config:
        from_attributes = True
