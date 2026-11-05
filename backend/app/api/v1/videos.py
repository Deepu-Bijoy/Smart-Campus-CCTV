import os
import uuid
import logging
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, Response, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload

from app.api import deps
from app.core.config import settings
from app.models.user import User
from app.models.video import Video
from app.schemas.video import VideoResponse, VideoStatusResponse
from app.services.video_metadata import extract_video_metadata, check_video_integrity
from app.tasks.video_tasks import process_video

logger = logging.getLogger(__name__)
router = APIRouter()

def resolve_camera_id(camera_id_val: Any, camera_rel: Any = None) -> Optional[uuid.UUID]:
    """
    Safely resolve camera UUID from relationship or database column,
    preventing Pydantic FieldInfo/Form descriptor strings or invalid data from leaking.
    """
    if camera_rel is not None and hasattr(camera_rel, "id") and isinstance(camera_rel.id, uuid.UUID):
        return camera_rel.id
    if isinstance(camera_id_val, uuid.UUID):
        return camera_id_val
    if isinstance(camera_id_val, str):
        if "annotation=" in camera_id_val or "alias=" in camera_id_val or "FieldInfo" in camera_id_val or "required=" in camera_id_val:
            return None
        try:
            return uuid.UUID(camera_id_val)
        except (ValueError, TypeError, AttributeError):
            return None
    return None

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
        max_size = settings.MAX_UPLOAD_SIZE_BYTES
        with open(saved_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > max_size:
                    buffer.close()
                    if os.path.exists(saved_path):
                        os.remove(saved_path)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Video upload size exceeds {settings.max_upload_size_formatted} limit ({settings.MAX_UPLOAD_SIZE_BYTES:,} bytes)."
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

    # Validate non-empty content
    if total_size == 0:
        if os.path.exists(saved_path):
            os.remove(saved_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded video file is empty (0 bytes)."
        )

    # Validate video stream integrity (detect corrupted or invalid containers)
    is_valid, corruption_detail = check_video_integrity(saved_path)
    if not is_valid:
        if os.path.exists(saved_path):
            os.remove(saved_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=corruption_detail or "Corrupted or unreadable video file."
        )

    # Deduplication check on client retry: if an active record already exists for identical upload within 120s
    from datetime import datetime, timezone, timedelta
    recent_cutoff = datetime.now(timezone.utc) - timedelta(seconds=120)
    dup_stmt = select(Video).filter(
        Video.uploaded_by == current_user.id,
        Video.original_filename == original_filename,
        Video.file_size == total_size,
        Video.created_at >= recent_cutoff,
        Video.status.in_(["queued", "processing", "completed"])
    ).order_by(Video.created_at.desc())
    dup_res = await db.execute(dup_stmt)
    existing_video = dup_res.scalars().first()
    if existing_video:
        logger.info(f"Duplicate upload detected on retry for video {original_filename}. Returning existing record {existing_video.id}.")
        if os.path.exists(saved_path):
            os.remove(saved_path)
        cam_id = resolve_camera_id(existing_video.camera_id, getattr(existing_video, "camera", None))
        return VideoResponse(
            id=existing_video.id,
            title=existing_video.title,
            filename=existing_video.filename,
            original_filename=existing_video.original_filename,
            file_path=existing_video.file_path,
            status=existing_video.status,
            duration=existing_video.duration,
            width=existing_video.width,
            height=existing_video.height,
            fps=existing_video.fps,
            codec=existing_video.codec,
            file_size=existing_video.file_size,
            current_stage=existing_video.current_stage,
            progress_percentage=existing_video.progress_percentage,
            processing_started_at=existing_video.processing_started_at,
            processing_finished_at=existing_video.processing_finished_at,
            error_message=existing_video.error_message,
            camera_id=cam_id,
            uploaded_by=existing_video.uploaded_by,
            created_at=existing_video.created_at,
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
        camera_id=resolve_camera_id(camera_id)
    )
    
    db.add(video)
    await db.commit()
    await db.refresh(video)
    
    logger.info(f"Video {video.id} saved in database. Dispatching processing task to Celery...")
    
    try:
        task_res = process_video.delay(str(video.id))
        if hasattr(task_res, "id") and task_res.id:
            from app.tasks.video_tasks import register_video_task
            register_video_task(str(video.id), task_res.id)
        logger.info(f"Task successfully dispatched to Celery for Video: {video.id}")

        # Check worker availability so queued jobs cannot silently stall without operator awareness
        from app.tasks.cel_app import get_celery_worker_status
        w_status = get_celery_worker_status(timeout=0.3)
        if not w_status.get("online"):
            logger.warning(f"Video {video.id} queued in Redis, but no Celery worker is consuming gpu_queue.")
            video.current_stage = "Queued (Worker Offline)"
            video.error_message = "Job queued to Redis gpu_queue, but no active Celery worker was detected on the host."
            await db.commit()
            await db.refresh(video)
    except Exception as e:
        logger.error(f"Failed to dispatch Celery task: {str(e)}")
        video.status = "failed"
        video.current_stage = "Queue Failure"
        video.error_message = f"Could not enqueue task: {str(e)}"
        await db.commit()
        await db.refresh(video)
    
    return VideoResponse(
        id=video.id,
        title=video.title,
        filename=video.filename,
        original_filename=video.original_filename,
        file_path=video.file_path,
        status=video.status,
        duration=video.duration,
        width=video.width,
        height=video.height,
        fps=video.fps,
        codec=video.codec,
        file_size=video.file_size,
        current_stage=video.current_stage,
        progress_percentage=video.progress_percentage,
        processing_started_at=video.processing_started_at,
        processing_finished_at=video.processing_finished_at,
        error_message=video.error_message,
        camera_id=video.camera_id,
        uploaded_by=video.uploaded_by,
        created_at=video.created_at,
    )

@router.get("", response_model=List[VideoResponse])
@router.get("/", response_model=List[VideoResponse])
async def list_videos(
    limit: Optional[int] = Query(None, ge=1),
    offset: Optional[int] = Query(None, ge=0),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    role = getattr(current_user, "role", "").lower()
    is_staff = role in ["admin", "operator"]
    
    stmt = select(Video).options(joinedload(Video.camera)).order_by(Video.created_at.desc())
    if not is_staff:
        uid_str = str(current_user.id)
        uid_hex = current_user.id.hex if hasattr(current_user.id, "hex") else uid_str.replace("-", "")
        stmt = stmt.filter(
            (Video.uploaded_by == current_user.id) |
            (Video.uploaded_by == uid_str) |
            (Video.uploaded_by == uid_hex)
        )
    
    if limit is not None and limit > 0:
        stmt = stmt.limit(limit)
    if offset is not None and offset > 0:
        stmt = stmt.offset(offset)

    result = await db.execute(stmt)
    videos = result.scalars().all()

    response_items: List[VideoResponse] = []
    for video in videos:
        cam_id = resolve_camera_id(video.camera_id, getattr(video, "camera", None))
        response_items.append(
            VideoResponse(
                id=video.id,
                title=video.title,
                filename=video.filename,
                original_filename=video.original_filename,
                file_path=video.file_path,
                status=video.status,
                duration=video.duration,
                width=video.width,
                height=video.height,
                fps=video.fps,
                codec=video.codec,
                file_size=video.file_size,
                current_stage=video.current_stage,
                progress_percentage=video.progress_percentage,
                processing_started_at=video.processing_started_at,
                processing_finished_at=video.processing_finished_at,
                error_message=video.error_message,
                camera_id=cam_id,
                uploaded_by=video.uploaded_by,
                created_at=video.created_at,
            )
        )
    return response_items

@router.get("/config")
@router.get("/upload-config")
async def get_video_upload_config() -> Any:
    """
    Returns the configured video upload limit and allowed video formats.
    """
    return {
        "max_upload_size_bytes": settings.MAX_UPLOAD_SIZE_BYTES,
        "max_upload_size_formatted": settings.max_upload_size_formatted,
        "allowed_formats": ["MP4", "AVI", "MKV", "MOV"]
    }

@router.get("/{video_id}", response_model=VideoResponse)
async def get_video(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    vid_str = str(video_id)
    vid_hex = video_id.hex if hasattr(video_id, "hex") else vid_str.replace("-", "")
    result = await db.execute(
        select(Video).options(joinedload(Video.camera)).filter(
            (Video.id == video_id) | (Video.id == vid_str) | (Video.id == vid_hex)
        )
    )
    video = result.scalars().first()
    if not video:
        logger.warning(f"Video {video_id} not found")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    role = getattr(current_user, "role", "").lower()
    is_staff = role in ["admin", "operator"]
    uid_hex = current_user.id.hex if hasattr(current_user.id, "hex") else str(current_user.id).replace("-", "")
    video_uploader_hex = str(video.uploaded_by).replace("-", "")
    if not is_staff and video_uploader_hex != uid_hex:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    cam_id = resolve_camera_id(video.camera_id, getattr(video, "camera", None))
    return VideoResponse(
        id=video.id,
        title=video.title,
        filename=video.filename,
        original_filename=video.original_filename,
        file_path=video.file_path,
        status=video.status,
        duration=video.duration,
        width=video.width,
        height=video.height,
        fps=video.fps,
        codec=video.codec,
        file_size=video.file_size,
        current_stage=video.current_stage,
        progress_percentage=video.progress_percentage,
        processing_started_at=video.processing_started_at,
        processing_finished_at=video.processing_finished_at,
        error_message=video.error_message,
        camera_id=cam_id,
        uploaded_by=video.uploaded_by,
        created_at=video.created_at,
    )

@router.get("/{video_id}/status", response_model=VideoStatusResponse)
async def get_video_status(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    vid_str = str(video_id)
    vid_hex = video_id.hex if hasattr(video_id, "hex") else vid_str.replace("-", "")
    result = await db.execute(
        select(Video).filter(
            (Video.id == video_id) | (Video.id == vid_str) | (Video.id == vid_hex)
        )
    )
    video = result.scalars().first()
    if not video:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
    stage = video.current_stage
    err_msg = video.error_message
    w_desc = None

    if video.status == "queued":
        from app.tasks.cel_app import get_celery_worker_status
        w_status = get_celery_worker_status(timeout=0.3)
        if not w_status.get("online"):
            w_desc = "Offline"
            stage = "Queued (Worker Offline - No Celery Worker on gpu_queue)"
            if not err_msg:
                err_msg = "No active Celery worker consuming gpu_queue. Start worker to process: celery -A app.tasks.cel_app.celery_app worker -Q gpu_queue,cpu_queue -P solo -l info"
        else:
            w_desc = "Online"

    return {
        "video_id": video.id,
        "status": video.status,
        "stage": stage,
        "progress": video.progress_percentage,
        "error_message": err_msg,
        "worker_status": w_desc
    }

@router.delete("/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_video(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> None:
    import shutil
    from app.models.track import Track, PersonReid, Detection
    from app.models.recognition import StudentRecognitionEvent
    from app.models.incident import Incident, DetectedEvent, Evidence, IncidentPerson
    from app.models.event import Event, EventTrack
    from app.tasks.video_tasks import cancel_video_processing
    from app.services.vector_store import QdrantVectorStore
    from qdrant_client.http import models as qdrant_models
    from sqlalchemy import func, text
    
    vid_str = str(video_id)
    vid_hex = video_id.hex if hasattr(video_id, "hex") else vid_str.replace("-", "")
    # Check if video exists at all (differentiating 404 vs 403)
    v_res = await db.execute(
        select(Video).filter(
            (Video.id == video_id) | (Video.id == vid_str) | (Video.id == vid_hex)
        )
    )
    video = v_res.scalars().first()
    if not video:
        logger.warning(f"Video {video_id} not found for deletion")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Video not found"
        )
        
    # Check authorization (owner or staff: admin/operator)
    role = getattr(current_user, "role", "").lower()
    is_staff = role in ["admin", "operator"]
    uid_hex = current_user.id.hex if hasattr(current_user.id, "hex") else str(current_user.id).replace("-", "")
    video_uploader_hex = str(video.uploaded_by).replace("-", "")
    if video_uploader_hex != uid_hex and not is_staff:
        logger.warning(f"User {current_user.id} unauthorized to delete video {video_id} uploaded by {video.uploaded_by}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to delete this surveillance feed."
        )

    # Immediately request cancellation of any active/queued background workers or Celery tasks
    cancel_video_processing(video_id)
            
    # Transactional atomic deletion in safe dependency order
    try:
        vid_str = str(video_id)
        
        # 1. Fetch counts before delete for logging
        t_count_res = await db.execute(
            select(func.count(Track.id)).filter(Track.video_id == video_id)
        )
        tracks_count = t_count_res.scalar() or 0
        
        e_count_res = await db.execute(
            select(func.count(DetectedEvent.id)).filter(DetectedEvent.video_id == video_id)
        )
        events_count = e_count_res.scalar() or 0
        

        # 2. Collect physical files to delete after database commit
        files_to_remove = set()
        if video.file_path and os.path.exists(video.file_path):
            files_to_remove.add(video.file_path)

        # Collect track keyframes and PersonReid crops
        tracks_res = await db.execute(select(Track.key_frame_path).filter(Track.video_id == video_id))
        for (kf,) in tracks_res.fetchall():
            if kf and os.path.exists(kf):
                files_to_remove.add(kf)

        reids_res = await db.execute(select(PersonReid.crop_path).filter(PersonReid.video_id == video_id))
        for (cp,) in reids_res.fetchall():
            if cp and os.path.exists(cp):
                files_to_remove.add(cp)

        # 3. Handle related incidents:
        # Only delete an incident (and its evidence) if no other video references it!
        det_events_res = await db.execute(
            select(DetectedEvent.incident_id).filter(
                DetectedEvent.video_id == video_id,
                DetectedEvent.incident_id.isnot(None)
            ).distinct()
        )
        cand_incident_ids = [r[0] for r in det_events_res.fetchall()]
        incidents_to_delete = []
        for inc_id in cand_incident_ids:
            other_refs = (await db.execute(
                select(func.count(DetectedEvent.id)).filter(
                    DetectedEvent.incident_id == inc_id,
                    DetectedEvent.video_id != video_id
                )
            )).scalar() or 0
            if other_refs == 0:
                incidents_to_delete.append(inc_id)
                ev_res = await db.execute(
                    select(Evidence.file_path).filter(Evidence.incident_id == inc_id)
                )
                for (ef,) in ev_res.fetchall():
                    if ef and os.path.exists(ef):
                        files_to_remove.add(ef)

        vid_hex = video.id.hex if hasattr(video.id, "hex") else vid_str.replace("-", "")
        # A. event_tracks for tracks of this video or events of this video
        await db.execute(
            text("""DELETE FROM event_tracks 
                    WHERE track_id IN (SELECT id FROM tracks WHERE video_id = :vid OR video_id = :vid_hex)
                       OR event_id IN (SELECT id FROM events WHERE video_id = :vid OR video_id = :vid_hex)""").bindparams(vid=vid_str, vid_hex=vid_hex)
        )
        # B. events for this video
        await db.execute(
            text("DELETE FROM events WHERE video_id = :vid OR video_id = :vid_hex").bindparams(vid=vid_str, vid_hex=vid_hex)
        )
        # C. student_recognition_events for this video
        await db.execute(
            text("DELETE FROM student_recognition_events WHERE video_id = :vid OR video_id = :vid_hex").bindparams(vid=vid_str, vid_hex=vid_hex)
        )
        # D. person_reids for this video
        await db.execute(
            text("DELETE FROM person_reids WHERE video_id = :vid OR video_id = :vid_hex").bindparams(vid=vid_str, vid_hex=vid_hex)
        )
        # E. detections for tracks of this video
        await db.execute(
            text("DELETE FROM detections WHERE track_id IN (SELECT id FROM tracks WHERE video_id = :vid OR video_id = :vid_hex)").bindparams(vid=vid_str, vid_hex=vid_hex)
        )
        # F. tracks for this video
        await db.execute(
            text("DELETE FROM tracks WHERE video_id = :vid OR video_id = :vid_hex").bindparams(vid=vid_str, vid_hex=vid_hex)
        )
        # G. detected_events for this video
        await db.execute(
            text("DELETE FROM detected_events WHERE video_id = :vid OR video_id = :vid_hex").bindparams(vid=vid_str, vid_hex=vid_hex)
        )
        # H. Orphaned incidents
        for inc_id in incidents_to_delete:
            i_str = str(inc_id)
            await db.execute(text("UPDATE reports SET incident_id = NULL WHERE incident_id = :iid").bindparams(iid=i_str))
            await db.execute(text("DELETE FROM evidences WHERE incident_id = :iid").bindparams(iid=i_str))
            await db.execute(text("DELETE FROM incident_persons WHERE incident_id = :iid").bindparams(iid=i_str))
            await db.execute(text("DELETE FROM incidents WHERE id = :iid").bindparams(iid=i_str))

        # I. Delete video record itself
        await db.execute(text("DELETE FROM videos WHERE id = :vid OR id = :vid_hex").bindparams(vid=vid_str, vid_hex=vid_hex))

        # 5. Delete vectors from Qdrant
        try:
            qdrant_store = QdrantVectorStore()
            qdrant_store.delete_vectors_by_video_id(video_id)
        except Exception as qe:
            logger.error(f"Failed to clean up Qdrant CCTV vectors for video {video_id}: {str(qe)}")

        # Commit database transaction
        await db.commit()
        db.expire_all()

        # 6. Delete physical files and artifact directories from disk safely
        for fp in files_to_remove:
            try:
                if os.path.exists(fp):
                    os.remove(fp)
            except Exception as fe:
                logger.error(f"Failed to remove physical file {fp}: {str(fe)}")

        # Clean up video-specific crop directory if present
        v_crop_dir = os.path.join(settings.STORAGE_DIR, "crops", vid_str)
        if os.path.exists(v_crop_dir):
            shutil.rmtree(v_crop_dir, ignore_errors=True)

        # Clean up video-specific frames directory if present
        v_frame_dir = os.path.join(settings.STORAGE_DIR, "frames", vid_str)
        if os.path.exists(v_frame_dir):
            shutil.rmtree(v_frame_dir, ignore_errors=True)

        logger.info(f"Deleted video: video_id={video_id} Removed: Tracks: {tracks_count} Events: {events_count}")

    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.exception(f"Failed to delete video {video_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to delete this video because related analysis records could not be removed. No changes were committed."
        )

    return
