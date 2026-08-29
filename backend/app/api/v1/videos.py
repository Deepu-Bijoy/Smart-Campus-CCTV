import os
import uuid
import logging
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api import deps
from app.core.config import settings
from app.models.user import User
from app.models.video import Video
from app.schemas.video import VideoResponse, VideoStatusResponse
from app.services.video_metadata import extract_video_metadata
from app.tasks.video_tasks import process_video

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/upload", response_model=VideoResponse, status_code=status.HTTP_201_CREATED)
async def upload_video(
    title: Optional[str] = Form(None),
    camera_id: Optional[uuid.UUID] = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    # Ensure storage dir exists
    os.makedirs(settings.STORAGE_DIR, exist_ok=True)
    
    # Sanitize file name to prevent path traversal
    original_filename = os.path.basename(file.filename or "unknown_filename")
    file_extension = os.path.splitext(original_filename)[1]
    if not file_extension.lower() in [".mp4", ".avi", ".mkv", ".mov"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported video format. Allowed formats: MP4, AVI, MKV, MOV."
        )

    file_id = uuid.uuid4()
    saved_filename = f"{file_id}{file_extension}"
    saved_path = os.path.join(settings.STORAGE_DIR, saved_filename)
    
    resolved_title = title if title else os.path.splitext(original_filename)[0]
    logger.info(f"User {current_user.id} uploading video {original_filename} as {saved_filename}")
    
    try:
        total_size = 0
        max_size = 100 * 1024 * 1024  # 100MB limit
        with open(saved_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > max_size:
                    buffer.close()
                    if os.path.exists(saved_path):
                        os.remove(saved_path)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Video upload size exceeds 100MB limit."
                    )
                buffer.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to write uploaded file to disk: {str(e)}")
        if os.path.exists(saved_path):
            os.remove(saved_path)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write file to local disk: {str(e)}"
        )
        
    try:
        metadata = extract_video_metadata(saved_path)
    except Exception as e:
        logger.error(f"Metadata extraction crashed: {str(e)}")
        metadata = {
            "duration": None,
            "fps": None,
            "width": None,
            "height": None,
            "codec": None,
            "file_size": os.path.getsize(saved_path)
        }

    video = Video(
        id=file_id,
        title=resolved_title,
        filename=saved_filename,
        original_filename=original_filename,
        file_path=saved_path,
        status="queued",
        current_stage="Queued",
        progress_percentage=0,
        duration=metadata.get("duration"),
        width=metadata.get("width"),
        height=metadata.get("height"),
        fps=metadata.get("fps"),
        codec=metadata.get("codec"),
        file_size=metadata.get("file_size"),
        uploaded_by=current_user.id,
        camera_id=camera_id
    )
    
    db.add(video)
    await db.commit()
    await db.refresh(video)
    
    logger.info(f"Video {video.id} saved in database. Dispatching processing task to Celery...")
    
    try:
        process_video.delay(str(video.id))
        logger.info(f"Task successfully dispatched to Celery for Video: {video.id}")
    except Exception as e:
        logger.error(f"Failed to dispatch Celery task: {str(e)}")
        video.status = "failed"
        video.current_stage = "Queue Failure"
        video.error_message = f"Could not enqueue task: {str(e)}"
        await db.commit()
        await db.refresh(video)
    
    return video

@router.get("", response_model=List[VideoResponse])
@router.get("/", response_model=List[VideoResponse])
async def list_videos(
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    result = await db.execute(
        select(Video).filter(Video.uploaded_by == current_user.id).order_by(Video.created_at.desc())
    )
    return result.scalars().all()

@router.get("/{video_id}", response_model=VideoResponse)
async def get_video(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    result = await db.execute(
        select(Video).filter(Video.id == video_id, Video.uploaded_by == current_user.id)
    )
    video = result.scalars().first()
    if not video:
        logger.warning(f"Video {video_id} not found or access denied for user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    return video

@router.get("/{video_id}/status", response_model=VideoStatusResponse)
async def get_video_status(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    result = await db.execute(
        select(Video).filter(Video.id == video_id, Video.uploaded_by == current_user.id)
    )
    video = result.scalars().first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    return {
        "video_id": video.id,
        "status": video.status,
        "stage": video.current_stage,
        "progress": video.progress_percentage
    }

@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_video(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> None:
    from app.models.track import Track, PersonReid
    from app.models.recognition import StudentRecognitionEvent
    from app.models.incident import Incident, DetectedEvent, Evidence
    from app.services.vector_store import QdrantVectorStore
    from qdrant_client.http import models as qdrant_models
    from sqlalchemy import func
    
    result = await db.execute(
        select(Video).filter(Video.id == video_id, Video.uploaded_by == current_user.id)
    )
    video = result.scalars().first()
    if not video:
        logger.warning(f"Video {video_id} not found or access denied for deletion by user {current_user.id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
        
    if video.status == "processing":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete video while it is currently processing."
        )
        
    # Transactional atomic deletion
    try:
        # 1. Fetch counts before delete for logging
        t_count_res = await db.execute(
            select(func.count(Track.id)).filter(Track.video_id == video_id)
        )
        tracks_count = t_count_res.scalar() or 0
        
        e_count_res = await db.execute(
            select(func.count(DetectedEvent.id)).filter(DetectedEvent.video_id == video_id)
        )
        events_count = e_count_res.scalar() or 0
        
        qdrant_store = QdrantVectorStore()
        try:
            q_count = qdrant_store.client.count(
                collection_name=qdrant_store.collection_name,
                count_filter=qdrant_models.Filter(
                    must=[
                        qdrant_models.FieldCondition(
                            key="video_id",
                            match=qdrant_models.MatchValue(value=str(video_id))
                        )
                    ]
                ),
                exact=True
            )
            deleted_vectors_count = q_count.count
        except Exception:
            deleted_vectors_count = 0
            
        # 2. Get and clean related incidents & evidence files
        det_events_res = await db.execute(
            select(DetectedEvent).filter(DetectedEvent.video_id == video_id)
        )
        det_events = det_events_res.scalars().all()
        incident_ids = {de.incident_id for de in det_events if de.incident_id is not None}
        
        for inc_id in incident_ids:
            inc_res = await db.execute(
                select(Incident).filter(Incident.id == inc_id)
            )
            incident = inc_res.scalars().first()
            if incident:
                # Delete evidence physical files
                for ev in incident.evidences:
                    if os.path.exists(ev.file_path):
                        try:
                            os.remove(ev.file_path)
                        except Exception as fe:
                            logger.error(f"Failed to delete evidence file {ev.file_path}: {str(fe)}")
                await db.delete(incident)
                
        # 3. Clean up physical crop files from Track and PersonReid
        reids_res = await db.execute(
            select(PersonReid).filter(PersonReid.video_id == video_id)
        )
        reids = reids_res.scalars().all()
        for reid in reids:
            if os.path.exists(reid.crop_path):
                try:
                    os.remove(reid.crop_path)
                except Exception:
                    pass
                    
        tracks_res = await db.execute(
            select(Track).filter(Track.video_id == video_id)
        )
        tracks = tracks_res.scalars().all()
        for track in tracks:
            if track.key_frame_path and os.path.exists(track.key_frame_path):
                try:
                    os.remove(track.key_frame_path)
                except Exception:
                    pass
                    
        # 4. Delete CLIP embeddings from Qdrant
        try:
            qdrant_store.delete_vectors_by_video_id(video_id)
        except Exception as qe:
            logger.error(f"Failed to clean up Qdrant CCTV vectors for video {video_id}: {str(qe)}")
            
        # 5. Delete physical video file
        if os.path.exists(video.file_path):
            os.remove(video.file_path)
            
        # 6. Delete video record (cascades to Event, DetectedEvent, Track, PersonReid, StudentRecognitionEvent)
        await db.delete(video)
        await db.commit()
        
        # Log exact format requested
        logger.info(f"Deleted video: video_id={video_id} Removed: Tracks: {tracks_count} Events: {events_count} Qdrant vectors: {deleted_vectors_count}")
        
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete video {video_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete video: {str(e)}"
        )
        
    return
