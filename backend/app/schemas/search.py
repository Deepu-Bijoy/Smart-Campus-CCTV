import uuid
from typing import Optional, List, Dict
from pydantic import BaseModel, Field, ConfigDict

class SearchRequest(BaseModel):
    query: str = Field(..., description="Natural language search prompt", min_length=1)
    camera_id: Optional[str] = Field(None, description="Optional camera ID filter")
    video_id: Optional[uuid.UUID] = Field(None, description="Optional video ID filter")
    object_class: Optional[str] = Field(None, description="Optional object class filter (e.g., person, car)")
    start_time: Optional[float] = Field(None, description="Optional start time offset in seconds")
    end_time: Optional[float] = Field(None, description="Optional end time offset in seconds")
    top_k: int = Field(10, ge=1, le=100, description="Limit of search results to return")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "query": "a person in a black jacket carrying a backpack",
                "camera_id": "cam_1",
                "top_k": 10
            }
        }
    )

class SearchResult(BaseModel):
    track_id: uuid.UUID
    video_id: uuid.UUID
    camera_id: str
    timestamp: float
    confidence: float
    hybrid_score: float
    semantic_score: float
    identity_score: float
    temporal_score: float
    metadata_score: float

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "track_id": "c3b7a123-4567-89ab-cdef-0123456789ab",
                "video_id": "f8a9b123-4567-89ab-cdef-0123456789ab",
                "camera_id": "cam_1",
                "timestamp": 12.5,
                "confidence": 0.89,
                "hybrid_score": 0.82,
                "semantic_score": 0.78,
                "identity_score": 0.92,
                "temporal_score": 1.0,
                "metadata_score": 1.0
            }
        }
    )

class SearchResponse(BaseModel):
    results: List[SearchResult]

class ExplainResult(BaseModel):
    track_id: uuid.UUID
    video_id: uuid.UUID
    camera_id: str
    timestamp: float
    confidence: float
    hybrid_score: float
    scores: Dict[str, float]
    explanation: str
    reasons: List[str] = []
    explain_confidence: str = "medium"

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "track_id": "c3b7a123-4567-89ab-cdef-0123456789ab",
                "video_id": "f8a9b123-4567-89ab-cdef-0123456789ab",
                "camera_id": "cam_1",
                "timestamp": 12.5,
                "confidence": 0.89,
                "hybrid_score": 0.82,
                "scores": {
                    "semantic": 0.78,
                    "identity": 0.92,
                    "temporal": 1.0,
                    "metadata": 1.0
                },
                "explanation": "Matched 'person in black jacket' with semantic score of 0.78.",
                "reasons": ["• Same student identity", "• High semantic similarity"],
                "explain_confidence": "high"
            }
        }
    )

class ExplainResponse(BaseModel):
    results: List[ExplainResult]

class EvidenceResult(BaseModel):
    track_id: uuid.UUID
    event_id: Optional[uuid.UUID] = None
    event_type: Optional[str] = None
    confidence: str
    score: float
    reasons: List[str]

    model_config = ConfigDict(from_attributes=True)

class EvidenceResponse(BaseModel):
    results: List[EvidenceResult]

class SimilarRequest(BaseModel):
    track_id: uuid.UUID = Field(..., description="The source track ID to find similar tracks for")
    top_k: int = Field(10, ge=1, le=100, description="Limit of similar tracks to return")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "track_id": "c3b7a123-4567-89ab-cdef-0123456789ab",
                "top_k": 5
            }
        }
    )

class SimilarResult(BaseModel):
    track_id: uuid.UUID
    video_id: uuid.UUID
    object_class: str
    similarity_score: float
    start_time: float
    end_time: float

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "example": {
                "track_id": "a1b2c3d4-5678-90ab-cdef-1234567890ab",
                "video_id": "d5e6f7a8-90bc-def1-2345-67890abcdef1",
                "object_class": "person",
                "similarity_score": 0.945,
                "start_time": 4.2,
                "end_time": 18.6
            }
        }
    )

class SimilarResponse(BaseModel):
    results: List[SimilarResult]
