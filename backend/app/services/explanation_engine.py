import uuid
import logging
from datetime import datetime
from typing import Dict, Any, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.recognition import StudentRecognitionEvent
from app.models.student import Student
from app.models.event import Event, EventTrack
from app.models.camera import VirtualZone

logger = logging.getLogger(__name__)

class ExplanationEngine:
    @staticmethod
    async def explain_result(
        db: AsyncSession,
        track_id: uuid.UUID,
        semantic_score: float,
        appearance_score: float,  # OSNet similarity from search
        temporal_score: float,
        metadata_score: float,
        weights: Dict[str, float]
    ) -> Dict[str, Any]:
        # 1. Fetch Identity Score (ArcFace) from StudentRecognitionEvent
        identity_score = 0.0
        student_name = "Unknown Student"
        student_id = None
        
        rec_stmt = (
            select(StudentRecognitionEvent)
            .filter(StudentRecognitionEvent.track_id == track_id)
            .order_by(StudentRecognitionEvent.similarity_score.desc())
        )
        rec_res = await db.execute(rec_stmt)
        rec_event = rec_res.scalars().first()
        
        if rec_event:
            identity_score = float(rec_event.similarity_score)
            student_id = rec_event.student_id
            
            # Fetch student name
            stud_stmt = select(Student).filter(Student.id == student_id)
            stud_res = await db.execute(stud_stmt)
            stud_obj = stud_res.scalars().first()
            if stud_obj:
                student_name = stud_obj.name

        # 2. Fetch Zone Score from Event/EventTrack
        zone_score = 0.0
        zone_name = None
        
        event_stmt = (
            select(Event)
            .join(EventTrack, Event.id == EventTrack.event_id)
            .filter(EventTrack.track_id == track_id)
            .order_by(Event.timestamp.desc())
        )
        event_res = await db.execute(event_stmt)
        event_obj = event_res.scalars().first()
        
        if event_obj:
            zone_score = 1.0
            # Fetch zone name
            zone_stmt = select(VirtualZone).filter(VirtualZone.id == event_obj.zone_id)
            zone_db_res = await db.execute(zone_stmt)
            zone_obj = zone_db_res.scalars().first()
            if zone_obj:
                zone_name = zone_obj.name

        # 3. Calculate Final Hybrid Score using adjusted weights
        final_score = (
            weights.get("semantic", 0.4) * semantic_score +
            weights.get("identity", 0.2) * identity_score +
            weights.get("appearance", 0.2) * appearance_score +
            weights.get("temporal", 0.1) * temporal_score +
            weights.get("zone", 0.05) * zone_score +
            weights.get("metadata", 0.05) * metadata_score
        )

        # 4. Generate structured reason text list
        reasons = []
        if identity_score >= 0.60:
            reasons.append(f"• Same student identity: {student_name} (ArcFace: {identity_score:.2f})")
        if appearance_score >= 0.50:
            reasons.append(f"• Similar clothing & features (OSNet: {appearance_score:.2f})")
        if temporal_score >= 0.80:
            reasons.append("• Present in requested time range")
        if zone_score >= 0.50:
            zone_lbl = f" '{zone_name}'" if zone_name else ""
            reasons.append(f"• Crossed Fence Zone{zone_lbl}")
        if semantic_score >= 0.35:
            reasons.append(f"• High semantic similarity (CLIP: {semantic_score:.2f})")

        if not reasons:
            reasons.append("• Aligned with aggregate appearance description matches.")

        # Determine overall confidence
        if final_score >= 0.70:
            confidence = "high"
        elif final_score >= 0.50:
            confidence = "medium"
        else:
            confidence = "low"

        return {
            "semantic_score": semantic_score,
            "identity_score": identity_score,
            "appearance_score": appearance_score,
            "temporal_score": temporal_score,
            "zone_score": zone_score,
            "final_hybrid_score": final_score,
            "confidence": confidence,
            "student_id": student_id,
            "student_name": student_name,
            "reasons": reasons
        }
