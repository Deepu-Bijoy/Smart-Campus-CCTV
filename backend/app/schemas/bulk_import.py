import uuid
from datetime import datetime
from pydantic import BaseModel
from typing import Optional, Dict, Any

class BulkImportJobResponse(BaseModel):
    id: uuid.UUID
    status: str
    total_records: int
    processed_records: int
    successful_records: int
    failed_records: int
    current_roll_number: Optional[str]
    estimated_remaining_seconds: Optional[float]
    report: Dict[str, Any]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
