import uuid
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

class ViolenceSignalBreakdown(BaseModel):
    motion_dynamics: float = Field(0.0, description="Motion velocity score of active person bounding boxes")
    person_interaction: float = Field(0.0, description="Spatial proximity score between interacting persons")
    clip_similarity: float = Field(0.0, description="Semantic text-visual alignment score from CLIP")
    temporal_persistence: float = Field(0.0, description="Track overlap persistence in window")

class InvolvedStudentCard(BaseModel):
    student_id: Optional[uuid.UUID] = None
    name: str
    roll_number: Optional[str] = None
    department: Optional[str] = None
    programme: Optional[str] = None
    year: Optional[int] = None
    semester: Optional[int] = None
    section: Optional[str] = None
    class_name: Optional[str] = None
    profile_photo_url: Optional[str] = None
    similarity_score: float = 0.0
    confidence: str = "unidentified"  # "high", "medium", "unidentified"
    track_id: Optional[str] = None
    event_id: Optional[str] = None
    is_identified: bool = True

class SegmentTrackInfo(BaseModel):
    event_id: Optional[str] = None
    track_id: str
    tracker_id: int
    frame_number: int
    timestamp_seconds: float
    bounding_box: List[float]
    person_crop: Optional[str] = None
    confidence: float
    face_visible: bool = False
    identified_student: Optional[InvolvedStudentCard] = None

class ViolenceSegment(BaseModel):
    segment_id: str
    event_id: Optional[str] = None
    video_id: Optional[str] = None
    start_time: float
    end_time: float
    duration: float
    timestamp_display: str
    confidence: float
    severity: str  # "High", "Medium", "Low"
    breakdown: ViolenceSignalBreakdown
    explanation: str
    evidence_image: Optional[str] = None
    evidence_video: Optional[str] = None
    persons_count: int = 0
    students: List[InvolvedStudentCard] = []
    tracks: List[SegmentTrackInfo] = []

class StudentVerificationResult(BaseModel):
    student_name: str
    student_id: Optional[str] = None
    enrollment_status: str  # "RESOLVED_VALID_EMBEDDING", "ENROLLMENT_MISSING_EMBEDDINGS", "STUDENT_NOT_FOUND", "AMBIGUOUS_RECORDS"
    enrollment_error: Optional[str] = None
    face_detected: bool = False
    valid_embedding_generated: bool = False
    observed_in_violence_interval: bool = False
    direct_fight_evidence: bool = False
    identity_status: str  # "CONFIRMED", "UNRESOLVED", "NOT_OBSERVED", "SUB_THRESHOLD", "AMBIGUOUS", "FACE_NOT_USABLE"
    participation_status: str  # "CONFIRMED_PARTICIPANT", "IDENTIFIED_NEAR_INCIDENT", "POSSIBLE_PARTICIPANT_UNVERIFIED", "NOT_OBSERVED_IN_INCIDENT", "NO_VIOLENCE_DETECTED", "IDENTITY_UNRESOLVED"
    similarity_score: Optional[float] = None
    confidence: Optional[str] = None  # "high", "medium", "none"
    runner_up_identity: Optional[str] = None
    runner_up_similarity: Optional[float] = None
    margin: Optional[float] = None
    best_evidence_timestamp: Optional[float] = None
    best_evidence_frame: Optional[int] = None
    best_track_id: Optional[str] = None
    rejection_reason: Optional[str] = None
    source_frame_diagnostic: Optional[Dict[str, Any]] = None
    explanation: str

class TargetedParticipantVerification(BaseModel):
    video_id: Optional[str] = None
    video_filename: Optional[str] = None
    violence_detected: bool = False
    violence_intervals: List[Dict[str, Any]] = []
    overall_violence_confidence: float = 0.0
    ash: StudentVerificationResult
    jose_john: StudentVerificationResult
    track_ids: List[str] = []
    face_failures: List[Dict[str, Any]] = []
    candidate_evaluations: List[Dict[str, Any]] = []
    video_pass_metrics: Optional[Dict[str, Any]] = None
    diagnostic_details: Optional[Dict[str, Any]] = None
    verified_at: Optional[datetime] = None

class ViolenceAnalysisResponse(BaseModel):
    video_id: uuid.UUID
    video_title: str
    camera_id: Optional[uuid.UUID] = None
    camera_name: Optional[str] = None
    camera_location: Optional[str] = None
    status: str  # "VIOLENCE_DETECTED" | "NORMAL"
    verdict: str  # Human readable description
    overall_confidence: float
    total_segments: int
    segments: List[ViolenceSegment]
    primary_evidence_image: Optional[str] = None
    primary_evidence_video: Optional[str] = None
    identified_students: List[InvolvedStudentCard] = []
    incident_id: Optional[uuid.UUID] = None
    analyzed_at: datetime
    targeted_verification: Optional[TargetedParticipantVerification] = None

class ViolenceReportRequest(BaseModel):
    incident_id: Optional[uuid.UUID] = None
    event_id: Optional[uuid.UUID] = None
    video_id: Optional[uuid.UUID] = None
    title: Optional[str] = None
    additional_notes: Optional[str] = None

class ViolenceVideoUploadResponse(BaseModel):
    video_id: uuid.UUID
    title: str
    filename: str
    original_filename: str
    file_url: str
    status: str
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None
    codec: Optional[str] = None
    file_size: Optional[int] = None
    uploaded_at: datetime
