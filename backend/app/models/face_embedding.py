import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Float, DateTime, ForeignKey, JSON, ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base_class import Base

class StudentFaceEmbedding(Base):
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("students.id", ondelete="CASCADE"), nullable=False
    )
    photo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("student_photos.id", ondelete="CASCADE"), nullable=False
    )
    embedding: Mapped[list] = mapped_column(ARRAY(Float), nullable=False)
    model_version: Mapped[str] = mapped_column(String(100), default="buffalo_l", nullable=False)
    quality_score: Mapped[float] = mapped_column(Float, nullable=False)
    blur_score: Mapped[float] = mapped_column(Float, nullable=False)
    pose_yaw: Mapped[float] = mapped_column(Float, nullable=False)
    pose_pitch: Mapped[float] = mapped_column(Float, nullable=False)
    pose_roll: Mapped[float] = mapped_column(Float, nullable=False)
    face_bbox: Mapped[dict] = mapped_column(JSON, nullable=False)  # {"x1": float, "y1": float, ...}
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    student = relationship("Student")
    photo = relationship("StudentPhoto")
