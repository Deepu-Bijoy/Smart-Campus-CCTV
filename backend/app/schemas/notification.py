import uuid
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

class NotificationResponse(BaseModel):
    id: uuid.UUID
    title: str
    message: str
    severity: str
    is_read: bool
    created_at: datetime

    class Config:
        from_attributes = True

class NotificationPreferenceResponse(BaseModel):
    email_notifications: bool
    push_notifications: bool
    min_severity: str

    class Config:
        from_attributes = True

class NotificationPreferenceUpdate(BaseModel):
    email_notifications: Optional[bool] = None
    push_notifications: Optional[bool] = None
    min_severity: Optional[str] = None
