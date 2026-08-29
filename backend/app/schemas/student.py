import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, EmailStr, ConfigDict

class StudentBase(BaseModel):
    university_roll_number: str = Field(..., description="Unique university roll number", min_length=1)
    name: str = Field(..., description="Full name of the student", min_length=1)
    department: str = Field(..., description="Department (e.g., CSE, ECE)", min_length=1)
    programme: str = Field(..., description="Academic programme (e.g., B.Tech, M.Tech)", min_length=1)
    year: int = Field(..., ge=1, le=5, description="Academic year")
    semester: int = Field(..., ge=1, le=10, description="Academic semester")
    section: str = Field(..., description="Class section (e.g., A, B)", min_length=1)
    email: EmailStr = Field(..., description="University email address")
    phone: Optional[str] = Field(None, description="Optional contact number")
    status: str = Field("active", description="Status of student record (e.g., active, inactive)")
    embedding_generated: bool = Field(False, description="Whether face embeddings are generated")

class StudentCreate(StudentBase):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "university_roll_number": "UR20260401",
                "name": "Jane Doe",
                "department": "Computer Science",
                "programme": "B.Tech",
                "year": 3,
                "semester": 6,
                "section": "A",
                "email": "janedoe@university.edu",
                "phone": "+1234567890",
                "status": "active"
            }
        }
    )

class StudentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1)
    department: Optional[str] = Field(None, min_length=1)
    programme: Optional[str] = Field(None, min_length=1)
    year: Optional[int] = Field(None, ge=1, le=5)
    semester: Optional[int] = Field(None, ge=1, le=10)
    section: Optional[str] = Field(None, min_length=1)
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    status: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "Jane Smith",
                "year": 4,
                "semester": 7
            }
        }
    )

from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator

class StudentPhotoResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    photo_path: str
    view: str
    file_size: int
    mime_type: str
    md5_hash: str
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime

    @field_validator("photo_path", mode="after")
    @classmethod
    def normalize_slashes(cls, v: str) -> str:
        return v.replace("\\", "/")

    model_config = ConfigDict(from_attributes=True)

class StudentFaceSessionResponse(BaseModel):
    id: uuid.UUID
    student_id: uuid.UUID
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

class StudentResponse(StudentBase):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    photos: List[StudentPhotoResponse] = []
    face_sessions: List[StudentFaceSessionResponse] = []

    model_config = ConfigDict(from_attributes=True)

class StudentListResponse(BaseModel):
    total: int
    items: List[StudentResponse]

class EnrollmentSummaryResponse(BaseModel):
    processed: int
    successful: int
    failed: int
    quality_scores: Dict[str, float]
    errors: List[Dict[str, str]]

class EnrollmentStatusResponse(BaseModel):
    student_id: uuid.UUID
    photos_count: int
    embeddings_count: int
    missing_views: List[str]
    enrolled_views: List[str]
    quality_scores: Dict[str, float]
