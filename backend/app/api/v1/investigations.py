import uuid
import logging
from datetime import datetime, timezone
from typing import Any, List, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from app.api import deps
from app.models.user import User
from app.models.video import Video
from app.models.track import Track, Detection, PersonReid
from app.models.student import Student
from app.models.face_embedding import StudentFaceEmbedding
from app.models.recognition import StudentRecognitionEvent
from app.services.vector_store import QdrantVectorStore
from app.schemas.investigation import DashboardResponse, TimelineResponse, EvidenceResponse, TimelineItem
from app.schemas.track import TrackResponse, DetectionResponse
from app.schemas.recognition import StudentAppearanceResponse, TrackStudentResponse, VideoStudentsResponse

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard_metrics(
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Compile and return aggregated system-wide surveillance and enrollment statistics.
    """
    try:
        videos_count = (await db.execute(select(func.count(Video.id)))).scalar() or 0
        tracks_count = (await db.execute(select(func.count(Track.id)))).scalar() or 0
        detections_count = (await db.execute(select(func.count(Detection.id)))).scalar() or 0
        students_count = (await db.execute(select(func.count(Student.id)))).scalar() or 0
        embeddings_count = (await db.execute(select(func.count(StudentFaceEmbedding.id)))).scalar() or 0
        
        return {
            "total_videos": videos_count,
            "total_tracks": tracks_count,
            "total_detections": detections_count,
            "enrolled_students": students_count,
            "face_embeddings_count": embeddings_count,
            "system_status": "healthy"
        }
    except Exception as e:
        logger.error(f"Failed to fetch dashboard metrics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve dashboard aggregated metrics: {str(e)}"
        )

async def _build_student_timeline(student: Student, db: AsyncSession) -> List[TimelineItem]:
    items = []
    
    # 1. Enrollment Event
    items.append(
        TimelineItem(
            id=uuid.uuid4(),
            event_type="enrollment",
            timestamp=student.created_at,
            label="Profile Enrolled",
            description=f"Student profile registered for {student.name} ({student.university_roll_number}).",
            metadata={"department": student.department, "programme": student.programme}
        )
    )
    
    # 2. Fetch face embeddings
    emb_res = await db.execute(select(StudentFaceEmbedding).filter(StudentFaceEmbedding.student_id == student.id))
    embeddings = emb_res.scalars().all()
    
    # Check Qdrant for matching appearance/face events
    qdrant_store = QdrantVectorStore()
    matched_tracks = []
    
    for emb in embeddings:
        try:
            # Look up matching appearance tags in the cctv_embeddings index
            response = qdrant_store.client.query_points(
                collection_name=qdrant_store.collection_name,
                query=emb.embedding,
                limit=3,
                with_payload=True
            )
            for res in response.points:
                if res.score > 0.60:
                    matched_tracks.append(res)
        except Exception as qe:
            logger.warning(f"Skipping vector similarity timeline checks: {str(qe)}")
            
    # Add simulated or matched CCTV appearances
    for idx, match in enumerate(matched_tracks):
        track_id_str = match.payload.get("track_id", str(uuid.uuid4()))
        camera_id = match.payload.get("camera_id", "Camera-HQ")
        timestamp_sec = float(match.payload.get("timestamp", 0.0))
        
        items.append(
            TimelineItem(
                id=uuid.UUID(track_id_str) if isinstance(track_id_str, str) else uuid.uuid4(),
                event_type="detection",
                timestamp=datetime.now(timezone.utc),
                label="CCTV Face Match",
                description=f"Face matched similarity of {match.score:.2f} on camera {camera_id}.",
                metadata={"camera_id": camera_id, "confidence": float(match.score), "timestamp_seconds": timestamp_sec}
            )
        )
        
    return items

async def _build_track_timeline(track: Track, db: AsyncSession) -> List[TimelineItem]:
    items = []
    
    # Fetch detections
    det_res = await db.execute(
        select(Detection).filter(Detection.track_id == track.id).order_by(Detection.timestamp_seconds.asc())
    )
    detections = det_res.scalars().all()
    
    for det in detections:
        items.append(
            TimelineItem(
                id=det.id,
                event_type="detection",
                timestamp=det.created_at,
                label=f"Track {track.tracker_id} Detected",
                description=f"Trajectory active on frame {det.frame_number} at {det.timestamp_seconds:.1f}s.",
                metadata={
                    "frame_number": det.frame_number,
                    "timestamp_seconds": det.timestamp_seconds,
                    "bbox": det.bounding_box,
                    "confidence": det.confidence
                }
            )
        )
        
    return items

@router.get("/timeline/{target_id}", response_model=TimelineResponse)
async def get_target_timeline(
    target_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Dynamically resolve target_id to either a Student profile or a Track, compiling their chronologically sorted event timeline.
    """
    # 1. Test if target is a student
    student_res = await db.execute(select(Student).filter(Student.id == target_id))
    student = student_res.scalars().first()
    if student:
        items = await _build_student_timeline(student, db)
        return {"items": items}
        
    # 2. Test if target is a track
    track_res = await db.execute(select(Track).filter(Track.id == target_id))
    track = track_res.scalars().first()
    if track:
        items = await _build_track_timeline(track, db)
        return {"items": items}
        
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Timeline target ID {target_id} matches no active student profile or track."
    )

@router.get("/students/{id}/timeline", response_model=TimelineResponse)
async def get_student_timeline_alternate(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Direct alias endpoint to retrieve student-specific event timeline parameters.
    """
    student_res = await db.execute(select(Student).filter(Student.id == id))
    student = student_res.scalars().first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {id} not found."
        )
    items = await _build_student_timeline(student, db)
    return {"items": items}

@router.get("/evidence/{incident_id}", response_model=EvidenceResponse)
async def get_incident_evidence(
    incident_id: str,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Retrieve structured evidence details, logged severity indicators, and related track IDs associated with an incident.
    """
    # Since incident tables are pending, we return a structured simulator payload
    return {
        "incident_id": incident_id,
        "severity": "high" if "severe" in incident_id.lower() else "medium",
        "timestamp": datetime.now(timezone.utc),
        "summary": f"Aggregated evidence payload for campus security incident reference {incident_id}.",
        "media_assets": [
            {
                "asset_id": str(uuid.uuid4()),
                "type": "image/jpeg",
                "label": "Target Face Crop Match",
                "url": "/storage/crops/simulated_face.jpg"
            }
        ],
        "related_tracks": [uuid.uuid4()]
    }

@router.delete("/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evidence(
    evidence_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> None:
    """
    Remove a specific evidence record from the database and delete its physical media clip/crop on disk.
    """
    import os
    from app.models.incident import Evidence
    
    result = await db.execute(select(Evidence).filter(Evidence.id == evidence_id))
    evidence = result.scalars().first()
    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found"
        )
        
    try:
        # Delete local file
        if os.path.exists(evidence.file_path):
            os.remove(evidence.file_path)
            
        await db.delete(evidence)
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete evidence {evidence_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete evidence: {str(e)}"
        )
        
    return

@router.get("/videos/{id}/tracks", response_model=List[TrackResponse])
async def get_video_tracks(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    List all tracking trajectories registered for a specific video ID.
    """
    # Verify video existence
    video_res = await db.execute(select(Video).filter(Video.id == id))
    if not video_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video asset with ID {id} not found."
        )
        
    tracks_res = await db.execute(
        select(Track).filter(Track.video_id == id).order_by(Track.start_time.asc())
    )
    return tracks_res.scalars().all()

@router.get("/videos/{id}/detections", response_model=List[DetectionResponse])
async def get_video_detections(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    List all individual coordinate detections registered for a specific video ID.
    """
    # Verify video existence
    video_res = await db.execute(select(Video).filter(Video.id == id))
    if not video_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video asset with ID {id} not found."
        )
        
    det_res = await db.execute(
        select(Detection)
        .join(Track, Detection.track_id == Track.id)
        .filter(Track.video_id == id)
        .order_by(Detection.timestamp_seconds.asc())
    )
    return det_res.scalars().all()

@router.get("/students/{id}/appearances", response_model=List[StudentAppearanceResponse])
async def get_student_appearances(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    List all recorded CCTV video matches/recognition events for a specific student ID.
    """
    # Verify student exists
    student_res = await db.execute(select(Student).filter(Student.id == id))
    if not student_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {id} not found."
        )
        
    events_res = await db.execute(
        select(StudentRecognitionEvent)
        .filter(StudentRecognitionEvent.student_id == id)
        .order_by(StudentRecognitionEvent.timestamp.desc())
    )
    events = events_res.scalars().all()
    
    return [
        StudentAppearanceResponse(
            event_id=ev.id,
            track_id=ev.track_id,
            video_id=ev.video_id,
            timestamp=ev.timestamp,
            similarity_score=ev.similarity_score,
            confidence=ev.confidence,
            camera_id=ev.camera_id
        ) for ev in events
    ]

@router.get("/tracks/{track_id}/identified-student", response_model=Optional[TrackStudentResponse])
async def get_track_identified_student(
    track_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Retrieve the student identification match and confidence data for a specific person track ID.
    """
    # Verify track existence
    track_res = await db.execute(select(Track).filter(Track.id == track_id))
    track = track_res.scalars().first()
    if not track:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Track with ID {track_id} not found."
        )
        
    # Get the best match event (highest similarity score)
    event_res = await db.execute(
        select(StudentRecognitionEvent)
        .filter(StudentRecognitionEvent.track_id == track_id)
        .order_by(StudentRecognitionEvent.similarity_score.desc())
    )
    event = event_res.scalars().first()
    
    if not event:
        return TrackStudentResponse(
            track_id=track_id,
            student_id=None,
            student_name=None,
            similarity_score=None,
            confidence=None
        )
        
    student_res = await db.execute(select(Student).filter(Student.id == event.student_id))
    student = student_res.scalars().first()
    student_name = student.name if student else "Unknown Student"
    
    return TrackStudentResponse(
        track_id=track_id,
        student_id=event.student_id,
        student_name=student_name,
        similarity_score=event.similarity_score,
        confidence=event.confidence
    )

@router.get("/videos/{id}/identified-students", response_model=List[VideoStudentsResponse])
async def get_video_identified_students(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Compile a summary of all enrolled students identified in a specific processed video.
    """
    # Verify video existence
    video_res = await db.execute(select(Video).filter(Video.id == id))
    if not video_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Video asset with ID {id} not found."
        )
        
    # Query all events in this video grouped by student
    stmt = (
        select(
            Student.id,
            Student.name,
            Student.university_roll_number,
            func.count(StudentRecognitionEvent.id).label("appearances_count"),
            func.max(StudentRecognitionEvent.similarity_score).label("max_similarity")
        )
        .join(StudentRecognitionEvent, Student.id == StudentRecognitionEvent.student_id)
        .filter(StudentRecognitionEvent.video_id == id)
        .group_by(Student.id, Student.name, Student.university_roll_number)
    )
    result = await db.execute(stmt)
    rows = result.all()
    
    output = []
    from app.core.config import settings
    for row in rows:
        score = row.max_similarity
        if score >= settings.RECOGNITION_HIGH_THRESHOLD:
            confidence = "high"
        elif score >= settings.RECOGNITION_MEDIUM_THRESHOLD:
            confidence = "medium"
        else:
            confidence = "unknown"
            
        output.append(
            VideoStudentsResponse(
                student_id=row.id,
                student_name=row.name,
                roll_number=row.university_roll_number,
                appearances_count=row.appearances_count,
                max_similarity=row.max_similarity,
                confidence=confidence
            )
        )
        
    return output

from pydantic import BaseModel

class InvestigationQueryRequest(BaseModel):
    query: str

@router.post("/investigations/query")
async def query_investigations(
    request: InvestigationQueryRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Forensic Natural Language Incident Investigation query.
    """
    try:
        from app.services.investigation_service import IncidentInvestigationQueryEngine
        results = await IncidentInvestigationQueryEngine.query_incidents(db, request.query)
        return {"results": results}
    except Exception as e:
        logger.error(f"Investigation query failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to execute investigation query: {str(e)}"
        )


class IdentitySearchRequest(BaseModel):
    query: str
    camera_id: Optional[str] = None

@router.post("/investigations/search/identity")
async def search_identity(
    request: IdentitySearchRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Forensic Student Name/Identity CCTV Search and Appearance Timeline retrieval.
    """
    query = request.query.strip()
    logger.info(f"Student identity search query received: '{query}', camera_id={request.camera_id}")

    # 1. Extract student name token by stripping prefix keywords
    name_query = query.strip().rstrip("?.!")
    for prefix in ["find all appearances of", "find appearances of", "where was", "seen near", "seen", "find", "show"]:
        if name_query.lower().startswith(prefix):
            name_query = name_query[len(prefix):].strip()
    for suffix in ["seen near", "seen"]:
        if name_query.lower().endswith(suffix):
            name_query = name_query[:-len(suffix)].strip()

    # 2. Resolve Student from database
    from app.models.student import Student
    stmt = select(Student).filter(
        (Student.name.ilike(f"%{name_query}%")) | 
        (Student.university_roll_number.ilike(f"%{name_query}%"))
    )
    res = await db.execute(stmt)
    student = res.scalars().first()

    if not student:
        logger.info(f"No student matching query token '{name_query}' found in registry.")
        return {
            "type": "identity",
            "student": None,
            "appearances": []
        }

    # 3. Retrieve student face recognition events
    from app.models.recognition import StudentRecognitionEvent
    ev_stmt = select(StudentRecognitionEvent).filter(
        StudentRecognitionEvent.student_id == student.id
    )
    if request.camera_id:
        ev_stmt = ev_stmt.filter(StudentRecognitionEvent.camera_id == str(request.camera_id))
        
    ev_stmt = ev_stmt.order_by(StudentRecognitionEvent.timestamp.desc())
    ev_res = await db.execute(ev_stmt)
    events = ev_res.scalars().all()

    # 4. Construct appearance timeline with crops and videos
    from app.models.camera import Camera
    from app.models.video import Video
    from app.models.track import PersonReid

    appearances = []
    for ev in events:
        # Resolve Camera details
        camera_display = "Unknown Camera"
        if ev.camera_id:
            try:
                cam_uuid = uuid.UUID(ev.camera_id)
                cam_stmt = select(Camera).filter(Camera.id == cam_uuid)
            except ValueError:
                cam_stmt = select(Camera).filter((Camera.name == ev.camera_id) | (Camera.location == ev.camera_id))
                
            cam_res = await db.execute(cam_stmt)
            camera = cam_res.scalars().first()
            if camera:
                camera_display = f"{camera.name} ({camera.location})"
            else:
                camera_display = ev.camera_id

        # Resolve Video details
        video_url = None
        vid_stmt = select(Video).filter(Video.id == ev.video_id)
        vid_res = await db.execute(vid_stmt)
        video = vid_res.scalars().first()
        if video:
            video_url = video.file_path.replace("\\", "/")
            if "storage/" in video_url:
                video_url = "/" + video_url[video_url.find("storage/"):]

        # Resolve PersonReid crop path for evidence frame
        crop_url = None
        reid_stmt = select(PersonReid).filter(PersonReid.track_id == ev.track_id).order_by(PersonReid.timestamp_seconds.asc())
        reid_res = await db.execute(reid_stmt)
        reids = reid_res.scalars().all()
        if reids:
            # Pick first available crop as key frame crop path
            crop_path = reids[0].crop_path
            crop_url = crop_path.replace("\\", "/")
            if "storage/" in crop_url:
                crop_url = "/" + crop_url[crop_url.find("storage/"):]

        time_str = ev.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        appearances.append({
            "camera": camera_display,
            "timestamp": time_str,
            "track_id": str(ev.track_id),
            "recognition_confidence": float(ev.similarity_score),
            "video_id": str(ev.video_id),
            "evidence": {
                "image": crop_url,
                "video": video_url
            }
        })

    return {
        "type": "identity",
        "student": {
            "name": student.name,
            "class": f"{student.programme} {student.section}",
            "roll_number": student.university_roll_number
        },
        "appearances": appearances
    }


class AppearanceSearchRequest(BaseModel):
    query: str
    camera_id: Optional[str] = None

@router.post("/investigations/search/appearance")
async def search_appearance(
    request: AppearanceSearchRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Forensic Appearance/Clothing CCTV Search with ArcFace verification.
    """
    query = request.query.strip()
    logger.info(f"Appearance search query received: '{query}', camera_id={request.camera_id}")

    from app.services.vector_store import QdrantVectorStore
    from app.pipeline.embedder import CLIPEmbedder
    from app.models.recognition import StudentRecognitionEvent
    from app.models.student import Student
    from app.models.camera import Camera
    from app.models.video import Video
    from app.models.track import PersonReid

    # 1. Fetch matches from Qdrant cctv_embeddings
    vector_store = QdrantVectorStore()
    embedder = CLIPEmbedder()
    
    matches = vector_store.search_by_text(
        text_query=query,
        embedder=embedder,
        limit=100,
        camera_id=str(request.camera_id) if request.camera_id else None
    )

    if not matches:
        logger.info("No appearance matches returned from Qdrant.")
        return {
            "type": "appearance",
            "query": query,
            "results": []
        }

    # 2. Group by track_id to remove duplicate frames (sifting highest score match per track)
    grouped_matches = {}
    for m in matches:
        t_id = m["payload"]["track_id"]
        if t_id not in grouped_matches or m["score"] > grouped_matches[t_id]["score"]:
            grouped_matches[t_id] = m

    # 3. Calculate OSNet visual Re-ID prototype vector over top 3 matched tracks
    import numpy as np
    prototype_vectors = []
    for t_id in list(grouped_matches.keys())[:3]:
        stmt = select(PersonReid.embedding).filter(
            PersonReid.track_id == uuid.UUID(t_id)
        )
        r_res = await db.execute(stmt)
        embeddings = r_res.scalars().all()
        if embeddings:
            prototype_vectors.append(np.mean([np.array(e) for e in embeddings], axis=0))

    if prototype_vectors:
        avg_vec = np.mean(prototype_vectors, axis=0)
        reid_prototype = avg_vec / np.linalg.norm(avg_vec)
    else:
        reid_prototype = None

    # 4. Process each track, score, and check biometric status
    results = []
    for t_id, match in grouped_matches.items():
        payload = match["payload"]
        clip_score = float(match["score"])
        track_uuid = uuid.UUID(t_id)

        # A. Calculate OSNet similarity against prototype
        osnet_similarity = 0.0
        if reid_prototype is not None:
            stmt = select(PersonReid.embedding).filter(PersonReid.track_id == track_uuid)
            r_res = await db.execute(stmt)
            track_embeddings = r_res.scalars().all()
            if track_embeddings:
                similarities = []
                for emb in track_embeddings:
                    emb_arr = np.array(emb)
                    sim = np.dot(emb_arr, reid_prototype)
                    similarities.append(sim)
                osnet_similarity = float(max(similarities))

        # B. Check Biometric registry validation
        rec_stmt = select(StudentRecognitionEvent).filter(
            StudentRecognitionEvent.track_id == track_uuid
        ).order_by(StudentRecognitionEvent.similarity_score.desc())
        rec_res = await db.execute(rec_stmt)
        rec_event = rec_res.scalars().first()

        identity_status = "Unknown Person"
        student_data = None
        face_confidence = 0.0
        identity_bonus = 0.0

        if rec_event and rec_event.similarity_score >= 0.60:
            # Verified biometrics
            face_confidence = float(rec_event.similarity_score)
            std_stmt = select(Student).filter(Student.id == rec_event.student_id)
            std_res = await db.execute(std_stmt)
            student = std_res.scalars().first()
            if student:
                identity_status = "Identified"
                student_data = {
                    "name": student.name,
                    "class": f"{student.programme} {student.section}",
                    "roll_number": student.university_roll_number
                }
                identity_bonus = 0.05 * face_confidence

        # C. Calculate final ranked Appearance score
        final_score = (0.7 * clip_score) + (0.3 * osnet_similarity) + identity_bonus

        # D. Format Camera details
        camera_display = "Unknown Camera"
        cam_id = payload.get("camera_id")
        if cam_id:
            try:
                cam_uuid = uuid.UUID(cam_id)
                cam_stmt = select(Camera).filter(Camera.id == cam_uuid)
            except ValueError:
                cam_stmt = select(Camera).filter((Camera.name == cam_id) | (Camera.location == cam_id))
            cam_res = await db.execute(cam_stmt)
            camera = cam_res.scalars().first()
            if camera:
                camera_display = f"{camera.name} ({camera.location})"
            else:
                camera_display = cam_id

        # E. Format Video details
        video_url = None
        vid_id = payload.get("video_id")
        if vid_id:
            vid_stmt = select(Video).filter(Video.id == uuid.UUID(vid_id))
            vid_res = await db.execute(vid_stmt)
            video = vid_res.scalars().first()
            if video:
                video_url = video.file_path.replace("\\", "/")
                if "storage/" in video_url:
                    video_url = "/" + video_url[video_url.find("storage/"):]

        # F. Format Crop image details
        crop_url = None
        crop_path = payload.get("crop_path")
        if crop_path:
            crop_url = crop_path.replace("\\", "/")
            if "storage/" in crop_url:
                crop_url = "/" + crop_url[crop_url.find("storage/"):]

        # Extract timestamp string
        offset_seconds = float(payload.get("timestamp", 0.0))
        m, s = divmod(int(offset_seconds), 60)
        h, m = divmod(m, 60)
        time_str = f"{h:02d}:{m:02d}:{s:02d}"

        results.append({
            "track_id": t_id,
            "camera_name": camera_display,
            "timestamp": time_str,
            "semantic_score": clip_score,
            "osnet_score": osnet_similarity,
            "face_confidence": face_confidence,
            "final_score": final_score,
            "identity_status": identity_status,
            "student": student_data,
            "evidence": {
                "image": crop_url,
                "video": video_url
            }
        })

    # Sort results by final ranking score descending
    results.sort(key=lambda x: x["final_score"], reverse=True)

    return {
        "type": "appearance",
        "query": query,
        "results": results
    }


class UnifiedSearchRequest(BaseModel):
    query: str
    camera_id: Optional[str] = None

@router.post("/investigations/search")
async def unified_search(
    request: UnifiedSearchRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Unified Intelligent Search Router coordinating Identity, Appearance, and Incident inquiries.
    """
    query = request.query.strip()
    
    # 1. Classify the query using query_router classifier
    from app.services.query_router import classify_query
    query_type = classify_query(query)
    
    unified_results = []
    
    if query_type == "identity":
        # Delegate to Identity search pipeline
        search_req = IdentitySearchRequest(query=query, camera_id=request.camera_id)
        id_res = await search_identity(search_req, db, current_user)
        student_data = id_res["student"]
        
        for app_item in id_res["appearances"]:
            unified_results.append({
                "student": student_data,
                "camera": app_item["camera"],
                "timestamp": app_item["timestamp"],
                "confidence": app_item["recognition_confidence"],
                "match_reason": f"Matched because ArcFace recognition confidence was {app_item['recognition_confidence']:.2f}",
                "evidence": app_item["evidence"]
            })
            
    elif query_type == "appearance":
        # Delegate to Appearance search pipeline
        search_req = AppearanceSearchRequest(query=query, camera_id=request.camera_id)
        app_res = await search_appearance(search_req, db, current_user)
        
        for track_item in app_res["results"]:
            unified_results.append({
                "student": track_item["student"],
                "camera": track_item["camera_name"],
                "timestamp": track_item["timestamp"],
                "confidence": track_item["final_score"],
                "match_reason": f"Matched because CLIP similarity {track_item['semantic_score']:.2f} and OSNet appearance similarity {track_item['osnet_score']:.2f}",
                "evidence": track_item["evidence"]
            })
            
    elif query_type == "incident":
        # Delegate to Incident search pipeline
        from app.services.investigation_service import IncidentInvestigationQueryEngine
        import uuid
        cam_uuid = None
        if request.camera_id:
            try:
                cam_uuid = uuid.UUID(request.camera_id)
            except ValueError:
                pass
        inc_results = await IncidentInvestigationQueryEngine.query_incidents(db, query, camera_id=cam_uuid)
        
        for inc_item in inc_results:
            student_data = None
            all_students = []
            
            # Populate all identified engaged students from persons list
            if inc_item.get("persons"):
                for p in inc_item["persons"]:
                    if p.get("identity_status") == "Identified":
                        s_info = {
                            "name": p["name"],
                            "class": p["class_name"],
                            "roll_number": p["roll_number"],
                            "department": p.get("department", "N/A")
                        }
                        all_students.append(s_info)
                        if not student_data:
                            student_data = s_info

            if not student_data and inc_item["person"]["identity_status"] == "Identified":
                student_data = {
                    "name": inc_item["person"]["name"],
                    "class": inc_item["person"]["class_name"],
                    "roll_number": inc_item["person"]["roll_number"],
                    "department": inc_item["person"].get("department", "N/A")
                }
                all_students.append(student_data)
            
            time_display = f"{inc_item['timestamp']['date']} {inc_item['timestamp']['time']}"
            
            # Format match reason to explicitly list engaged students
            if all_students:
                names_formatted = ", ".join([f"{s['name']} (Roll: {s['roll_number']})" for s in all_students])
                match_reason = f"Detected {inc_item['incident_type'].lower()} incident. Engaged student(s) identified from directory: {names_formatted}. {inc_item['explanation']}"
            else:
                match_reason = inc_item["explanation"]

            unified_results.append({
                "student": student_data,
                "students": all_students,
                "camera": f"{inc_item['camera']['name']} ({inc_item['camera']['location']})",
                "timestamp": time_display,
                "confidence": float(inc_item["confidence"]["event_confidence"]),
                "match_reason": match_reason,
                "evidence": {
                    "image": inc_item["evidence"]["screenshot"],
                    "image_id": inc_item["evidence"].get("screenshot_id"),
                    "video": inc_item["evidence"]["video_clip"],
                    "video_id": inc_item["evidence"].get("video_clip_id")
                }
            })

    return {
        "query": query,
        "query_type": query_type,
        "results": unified_results
    }
