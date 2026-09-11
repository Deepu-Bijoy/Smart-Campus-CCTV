import os
import re
import uuid
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from app.api import deps
from app.core.config import settings
from app.models.user import User
from app.models.video import Video
from app.models.camera import Camera
from app.models.student import Student, StudentPhoto
from app.models.track import Track, Detection, PersonReid
from app.models.recognition import StudentRecognitionEvent
from app.models.incident import Incident, IncidentPerson, Evidence, DetectedEvent
from app.models.report import Report
from app.services.video_metadata import extract_video_metadata
from app.services.clip_generator import generate_subclip, extract_evidence_frame
from app.services.vector_store import QdrantVectorStore
from app.pipeline.x3d_violence_detector import X3DViolenceDetector
from app.pipeline.detector import YOLOv8Detector
from app.pipeline.tracker import ByteTrackTracker
from app.services.student_identifier import StudentIdentifier
from app.event_engine.event_engine import EventDetectionEngine
import cv2
from app.schemas.violence import (
    ViolenceAnalysisResponse,
    ViolenceSegment,
    ViolenceSignalBreakdown,
    InvolvedStudentCard,
    ViolenceReportRequest,
    ViolenceVideoUploadResponse,
    SegmentTrackInfo
)

logger = logging.getLogger(__name__)
router = APIRouter()

def _clean_storage_url(file_path: Optional[str]) -> Optional[str]:
    if not file_path:
        return None
    url = file_path.replace("\\", "/")
    if "storage/" in url:
        return "/" + url[url.find("storage/"):]
    if url.startswith("/"):
        return url
    return f"/{url}"

async def _get_student_profile_photo_url(db: AsyncSession, student_id: uuid.UUID) -> Optional[str]:
    photo_stmt = (
        select(StudentPhoto)
        .filter(StudentPhoto.student_id == student_id)
        .order_by(StudentPhoto.created_at.asc())
    )
    res = await db.execute(photo_stmt)
    photos = res.scalars().all()
    if not photos:
        return None
    # Prefer front view if available
    front_photo = next((p for p in photos if p.view.lower() == "front"), None)
    selected_photo = front_photo or photos[0]
    return _clean_storage_url(selected_photo.photo_path)

def check_video_integrity(file_path: str) -> tuple[bool, Optional[str]]:
    if not os.path.exists(file_path):
        return False, "File was not saved properly on server disk."
    
    if os.path.getsize(file_path) == 0:
        return False, "Video file is empty (0 bytes)."
        
    try:
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            return False, "Corrupted or invalid video stream. OpenCV could not open container."
        
        ret, frame = cap.read()
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        if not ret or frame is None or width <= 0 or height <= 0:
            return False, "Corrupted or unreadable video file. Video stream has no decodable frames."
            
        return True, None
    except Exception as e:
        return False, f"Error inspecting video codec/stream: {str(e)}"

@router.post("/upload", response_model=ViolenceVideoUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_violence_video(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    camera_id: Optional[uuid.UUID] = Form(None),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Dedicated video upload endpoint for the Violence Detection module.
    Validates file extension, size limit (100MB), and video stream integrity (non-corrupt).
    Stores video securely in storage directory, extracts metadata, creates Video record,
    and returns unique video_id without initiating general background Celery task.
    """
    os.makedirs(settings.STORAGE_DIR, exist_ok=True)
    original_filename = os.path.basename(file.filename or "unknown_cctv.mp4")
    file_extension = os.path.splitext(original_filename)[1].lower()
    
    # 1. Validate File Type
    if file_extension not in [".mp4", ".avi", ".mkv", ".mov"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported video format '{file_extension}'. Allowed formats: MP4, AVI, MKV, MOV."
        )

    file_id = uuid.uuid4()
    saved_filename = f"{file_id}{file_extension}"
    saved_path = os.path.join(settings.STORAGE_DIR, saved_filename)
    resolved_title = title if title else f"Violence Analysis - {os.path.splitext(original_filename)[0]}"
    
    # 2. Validate File Size & Save Stream
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
        if os.path.exists(saved_path):
            os.remove(saved_path)
        logger.error(f"Failed to write uploaded file to disk: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write video file to disk: {str(e)}"
        )

    if total_size == 0:
        if os.path.exists(saved_path):
            os.remove(saved_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded video file is empty (0 bytes)."
        )

    # 3. Validate Video Stream Integrity (detect corrupted files)
    is_valid, corruption_detail = check_video_integrity(saved_path)
    if not is_valid:
        if os.path.exists(saved_path):
            os.remove(saved_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=corruption_detail or "Corrupted or unreadable video file."
        )

    # 4. Extract Video Metadata
    try:
        metadata = extract_video_metadata(saved_path)
    except Exception as e:
        logger.warning(f"Metadata extraction fallback: {str(e)}")
        metadata = {
            "duration": None,
            "fps": None,
            "width": None,
            "height": None,
            "codec": None,
            "file_size": total_size
        }

    # 5. Create Video record in DB
    video = Video(
        id=file_id,
        title=resolved_title,
        filename=saved_filename,
        original_filename=original_filename,
        file_path=saved_path,
        status="uploaded",
        current_stage="Ready for Violence Analysis",
        progress_percentage=100,
        duration=metadata.get("duration"),
        width=metadata.get("width"),
        height=metadata.get("height"),
        fps=metadata.get("fps"),
        codec=metadata.get("codec"),
        file_size=metadata.get("file_size") or total_size,
        uploaded_by=current_user.id,
        camera_id=camera_id
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)

    logger.info(f"Video {video.id} uploaded successfully for violence detection. File size: {video.file_size} bytes.")

    return ViolenceVideoUploadResponse(
        video_id=video.id,
        title=video.title,
        filename=video.filename,
        original_filename=video.original_filename,
        file_url=_clean_storage_url(video.file_path),
        status=video.status,
        duration=video.duration,
        width=video.width,
        height=video.height,
        fps=video.fps,
        codec=video.codec,
        file_size=video.file_size,
        uploaded_at=video.created_at
    )

@router.post("/analyze", response_model=ViolenceAnalysisResponse, status_code=status.HTTP_200_OK)
async def analyze_video_for_violence(
    file: Optional[UploadFile] = File(None),
    video_id: Optional[uuid.UUID] = Form(None),
    camera_id: Optional[uuid.UUID] = Form(None),
    title: Optional[str] = Form(None),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Dedicated Violence Detection Manual Analysis Workflow:
    Accepts CCTV footage or an existing video asset ID, executes person detection,
    ByteTrack tracking, ArcFace biometric matching, and multi-signal Fight/Violence
    detection. Returns an evidence dossier with timestamps, confidence breakdown,
    and identified enrolled student profiles.
    """
    if not file and not video_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either an uploaded video file or an existing video_id must be provided."
        )

    # 1. Resolve or Create Video Record
    target_video: Optional[Video] = None
    if file:
        os.makedirs(settings.STORAGE_DIR, exist_ok=True)
        original_filename = os.path.basename(file.filename or "unknown_cctv.mp4")
        file_extension = os.path.splitext(original_filename)[1].lower()
        if file_extension not in [".mp4", ".avi", ".mkv", ".mov"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported video format. Allowed formats: MP4, AVI, MKV, MOV."
            )

        new_file_id = uuid.uuid4()
        saved_filename = f"{new_file_id}{file_extension}"
        saved_path = os.path.join(settings.STORAGE_DIR, saved_filename)
        resolved_title = title if title else f"Violence Analysis - {os.path.splitext(original_filename)[0]}"

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
                            detail="Video file exceeds maximum 100MB size limit."
                        )
                    buffer.write(chunk)
        except HTTPException:
            raise
        except Exception as e:
            if os.path.exists(saved_path):
                os.remove(saved_path)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to write uploaded CCTV file to disk: {str(e)}"
            )

        if total_size == 0:
            if os.path.exists(saved_path):
                os.remove(saved_path)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded video file is empty (0 bytes)."
            )

        is_valid, corruption_detail = check_video_integrity(saved_path)
        if not is_valid:
            if os.path.exists(saved_path):
                os.remove(saved_path)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=corruption_detail or "Corrupted or unreadable video file."
            )

        metadata = extract_video_metadata(saved_path)
        target_video = Video(
            id=new_file_id,
            title=resolved_title,
            filename=saved_filename,
            original_filename=original_filename,
            file_path=saved_path,
            status="processing",
            current_stage="Violence Detection Pipeline",
            progress_percentage=20,
            duration=metadata.get("duration"),
            width=metadata.get("width"),
            height=metadata.get("height"),
            fps=metadata.get("fps"),
            codec=metadata.get("codec"),
            file_size=metadata.get("file_size"),
            uploaded_by=current_user.id,
            camera_id=camera_id
        )
        db.add(target_video)
        await db.commit()
        await db.refresh(target_video)

    elif video_id:
        v_res = await db.execute(select(Video).filter(Video.id == video_id))
        target_video = v_res.scalars().first()
        if not target_video:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Video with ID {video_id} not found."
            )
        if camera_id and not target_video.camera_id:
            target_video.camera_id = camera_id
            await db.commit()

    # 2. Resolve Camera
    resolved_camera: Optional[Camera] = None
    target_cam_id = target_video.camera_id or camera_id
    if target_cam_id:
        c_res = await db.execute(select(Camera).filter(Camera.id == target_cam_id))
        resolved_camera = c_res.scalars().first()

    if not resolved_camera:
        c_res = await db.execute(select(Camera))
        resolved_camera = c_res.scalars().first()

    if not resolved_camera:
        resolved_camera = Camera(
            id=uuid.uuid4(),
            name="Main Campus Surveillance",
            building="Administrative Block",
            floor=1,
            location="Central Courtyard",
            direction="North",
            resolution="1920x1080",
            status="active"
        )
        db.add(resolved_camera)
        await db.commit()
        await db.refresh(resolved_camera)

    cam_id_str = str(resolved_camera.id)

    # 3. Dedicated Pretrained X3D-M Violence Detection Workflow
    t_total_start = time.time()
    t_yolo_total = 0.0
    t_bytetrack_total = 0.0
    t_arcface_total = 0.0
    t_evidence_total = 0.0
    t_db_total = 0.0

    target_video.status = "processing"
    target_video.current_stage = "X3D-M Temporal Violence Detection"
    target_video.progress_percentage = 30
    await db.commit()

    # Step 1: Run Pretrained X3D-M Video Temporal Model
    t_x3d_load_start = time.time()
    x3d_detector = X3DViolenceDetector()
    t_x3d_load = time.time() - t_x3d_load_start

    x3d_res = x3d_detector.detect_violence(
        target_video.file_path,
        window_duration_sec=2.0,
        stride_sec=1.0,
        threshold=0.4,
        context_margin_sec=1.0
    )

    logger.info(f"[X3D] Model loading: {t_x3d_load:.3f} sec")
    logger.info(f"[X3D] Video preprocessing: {x3d_res.timings.get('video_preprocessing_sec', 0.0):.3f} sec")
    logger.info(f"[X3D] Violence inference: {x3d_res.timings.get('violence_inference_sec', 0.0):.3f} sec")
    logger.info(f"[X3D] Segment extraction: {x3d_res.timings.get('segment_extraction_sec', 0.0):.3f} sec")

    if not x3d_res.is_violent or len(x3d_res.segments) == 0:
        # Video classified as Normal campus activity — no violence detected
        logger.info("[YOLO] Processing: 0.000 sec")
        logger.info("[ByteTrack] Processing: 0.000 sec")
        logger.info("[ArcFace] Processing: 0.000 sec")
        logger.info("[Evidence] Generation: 0.000 sec")
        logger.info("[DB] Persistence: 0.000 sec")
        logger.info(f"[TOTAL] {time.time() - t_total_start:.3f} sec")

        target_video.status = "completed"
        target_video.current_stage = "Analysis Completed - Normal Activity"
        target_video.progress_percentage = 100
        await db.commit()
        return await _compile_violence_dossier(db, target_video, resolved_camera)

    # Step 2: Violence Detected — Process ONLY detected violence segments downstream
    target_video.current_stage = "Processing Violence Segments (YOLOv8 & ByteTrack)"
    target_video.progress_percentage = 60
    await db.commit()

    yolo_detector = YOLOv8Detector()
    tracker = ByteTrackTracker()
    identifier = StudentIdentifier()

    cap = cv2.VideoCapture(target_video.file_path)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    if fps <= 0:
        fps = 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    video_duration = target_video.duration or (total_frames / fps if fps > 0 else 0.0)

    # Track-level identity cache to avoid redundant ArcFace calls
    track_identity_cache: Dict[int, Optional[Dict[str, Any]]] = {}

    for seg_idx, seg in enumerate(x3d_res.segments):
        seg_start_sec = max(0.0, seg.start_time)
        seg_end_sec = min(video_duration, seg.end_time) if video_duration > 0 else seg.end_time
        start_frame_idx = int(seg_start_sec * fps)
        end_frame_idx = int(seg_end_sec * fps)

        logger.info(
            f"[VIOLENCE PIPELINE] Processing segment {seg_idx + 1}/{len(x3d_res.segments)}: "
            f"{seg_start_sec:.2f}s to {seg_end_sec:.2f}s (frames {start_frame_idx}-{end_frame_idx})"
        )

        # 2a. Run YOLOv8 + ByteTrack only on the segment frames
        t_yolo_start = time.time()
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame_idx)
        current_frame_idx = start_frame_idx

        segment_tracks: Dict[int, Dict[str, Any]] = {}

        while current_frame_idx <= end_frame_idx:
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            t_sec = current_frame_idx / fps

            t_bt_start = time.time()
            track_result = tracker.track_frame(yolo_detector, frame, persist=True)
            t_bytetrack_total += (time.time() - t_bt_start)

            if track_result is not None and track_result.boxes is not None:
                boxes = track_result.boxes
                for box in boxes:
                    cls_id = int(box.cls[0].item())
                    if cls_id != 0:  # Class 0: person
                        continue

                    conf = float(box.conf[0].item())
                    xyxy = box.xyxy[0].cpu().numpy().tolist()
                    tracker_id = int(box.id[0].item()) if box.id is not None else current_frame_idx

                    # Crop person box
                    h, w = frame.shape[:2]
                    x1, y1, x2, y2 = map(int, xyxy)
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    crop = frame[y1:y2, x1:x2] if (x2 > x1 and y2 > y1) else None

                    if tracker_id not in segment_tracks:
                        segment_tracks[tracker_id] = {
                            "detections": [],
                            "best_crop_path": None,
                            "best_conf": 0.0,
                            "start_time": t_sec,
                            "end_time": t_sec,
                        }

                    trk_entry = segment_tracks[tracker_id]
                    trk_entry["end_time"] = t_sec
                    trk_entry["detections"].append({
                        "frame_number": current_frame_idx,
                        "timestamp_seconds": round(t_sec, 2),
                        "bounding_box": [round(c, 1) for c in xyxy],
                        "confidence": round(conf, 4)
                    })

                    # Save best crop for ArcFace biometric recognition
                    if crop is not None and conf > trk_entry["best_conf"] and crop.shape[0] >= 40 and crop.shape[1] >= 20:
                        trk_entry["best_conf"] = conf
                        crop_filename = f"crop_seg_{seg_idx}_trk_{tracker_id}_{current_frame_idx}.jpg"
                        crop_dir = os.path.join(settings.STORAGE_DIR, "crops")
                        os.makedirs(crop_dir, exist_ok=True)
                        crop_path = os.path.join(crop_dir, crop_filename)
                        cv2.imwrite(crop_path, crop)
                        trk_entry["best_crop_path"] = crop_path

            current_frame_idx += 1

        t_yolo_total += (time.time() - t_yolo_start)

        # 2b. ArcFace Student Identification (only on segment tracks, with caching)
        t_arc_start = time.time()
        for trk_id, trk_data in segment_tracks.items():
            if trk_id not in track_identity_cache:
                matched_identity = None
                crop_p = trk_data.get("best_crop_path")
                if crop_p and os.path.exists(crop_p):
                    try:
                        match_res = await identifier.identify_face_in_crop(crop_p)
                        if match_res and match_res.get("success") and match_res.get("student_id"):
                            sim = match_res.get("similarity_score", 0.0)
                            if sim >= 0.50:  # Safe threshold
                                s_stmt = select(Student).filter(Student.id == match_res["student_id"])
                                s_res = await db.execute(s_stmt)
                                student_obj = s_res.scalars().first()
                                if student_obj:
                                    matched_identity = {
                                        "student": student_obj,
                                        "similarity_score": sim,
                                        "confidence": match_res.get("confidence", "high"),
                                    }
                    except Exception as fe:
                        logger.warning(f"[VIOLENCE PIPELINE] ArcFace matching error for track {trk_id}: {fe}")

                track_identity_cache[trk_id] = matched_identity

        t_arcface_total += (time.time() - t_arc_start)

        # 2c. Evidence Generation
        t_ev_start = time.time()
        os.makedirs(os.path.join(settings.STORAGE_DIR, "evidence"), exist_ok=True)

        mid_sec = (seg_start_sec + seg_end_sec) / 2.0
        frame_filename = f"evidence_frame_x3d_{target_video.id.hex[:8]}_seg{seg_idx}.jpg"
        frame_path = os.path.join(settings.STORAGE_DIR, "evidence", frame_filename)
        extract_evidence_frame(target_video.file_path, mid_sec, frame_path)

        clip_filename = f"clip_x3d_{target_video.id.hex[:8]}_seg{seg_idx}.mp4"
        clip_path = os.path.join(settings.STORAGE_DIR, "evidence", clip_filename)
        generate_subclip(target_video.file_path, seg_start_sec, seg.duration, clip_path)
        t_evidence_total += (time.time() - t_ev_start)

        # 2d. Database Persistence
        t_db_start = time.time()
        incident_id = uuid.uuid4()
        inc_obj = Incident(
            id=incident_id,
            incident_type="Violence",
            camera_id=resolved_camera.id,
            confidence=seg.confidence,
            timestamp=datetime.now(timezone.utc),
            explanation=(
                f"X3D-M video temporal model detected physical altercation from "
                f"{seg.start_time:.1f}s to {seg.end_time:.1f}s "
                f"(duration {seg.duration:.1f}s, confidence {seg.confidence * 100:.1f}%)."
            )
        )
        db.add(inc_obj)

        det_event = DetectedEvent(
            id=uuid.uuid4(),
            video_id=target_video.id,
            camera_id=resolved_camera.id,
            incident_id=incident_id,
            event_type="VIOLENCE",
            confidence=seg.confidence,
            timestamp=datetime.now(timezone.utc)
        )
        db.add(det_event)

        if os.path.exists(frame_path):
            db.add(Evidence(
                id=uuid.uuid4(),
                incident_id=incident_id,
                evidence_type="screenshot",
                file_path=frame_path,
                timestamp=datetime.now(timezone.utc)
            ))
        if os.path.exists(clip_path):
            db.add(Evidence(
                id=uuid.uuid4(),
                incident_id=incident_id,
                evidence_type="video",
                file_path=clip_path,
                timestamp=datetime.now(timezone.utc)
            ))

        for trk_id, trk_data in segment_tracks.items():
            t_uuid = uuid.uuid4()
            id_info = track_identity_cache.get(trk_id)
            matched_sid = id_info["student"].id if id_info else None

            db_track = Track(
                id=t_uuid,
                video_id=target_video.id,
                object_class="person",
                tracker_id=trk_id,
                start_time=trk_data["start_time"],
                end_time=trk_data["end_time"],
                identified_student_id=matched_sid,
                key_frame_path=trk_data.get("best_crop_path")
            )
            db.add(db_track)

            for d in trk_data["detections"]:
                db.add(Detection(
                    id=uuid.uuid4(),
                    track_id=t_uuid,
                    frame_number=d["frame_number"],
                    timestamp_seconds=d["timestamp_seconds"],
                    bounding_box=d["bounding_box"],
                    confidence=d["confidence"]
                ))

            if id_info:
                db.add(IncidentPerson(
                    id=uuid.uuid4(),
                    incident_id=incident_id,
                    student_id=matched_sid,
                    confidence=id_info["similarity_score"]
                ))

        await db.commit()
        t_db_total += (time.time() - t_db_start)

    cap.release()

    # Step 3: Complete timing instrumentation
    t_total = time.time() - t_total_start
    logger.info(f"[YOLO] Processing: {t_yolo_total:.3f} sec")
    logger.info(f"[ByteTrack] Processing: {t_bytetrack_total:.3f} sec")
    logger.info(f"[ArcFace] Processing: {t_arcface_total:.3f} sec")
    logger.info(f"[Evidence] Generation: {t_evidence_total:.3f} sec")
    logger.info(f"[DB] Persistence: {t_db_total:.3f} sec")
    logger.info(f"[TOTAL] {t_total:.3f} sec")

    target_video.status = "completed"
    target_video.current_stage = "Violence Analysis Completed"
    target_video.progress_percentage = 100
    await db.commit()

    return await _compile_violence_dossier(db, target_video, resolved_camera)

async def _compile_violence_dossier(
    db: AsyncSession,
    target_video: Video,
    resolved_camera: Optional[Camera]
) -> ViolenceAnalysisResponse:
    # Compile Violence Analysis Dossier from database Incidents & DetectedEvents
    inc_stmt = (
        select(Incident)
        .join(DetectedEvent, Incident.id == DetectedEvent.incident_id)
        .options(
            selectinload(Incident.persons).selectinload(IncidentPerson.student),
            selectinload(Incident.evidences),
            selectinload(Incident.events)
        )
        .filter(
            DetectedEvent.video_id == target_video.id,
            Incident.incident_type.in_(["Fight", "Violence"])
        )
        .order_by(Incident.timestamp.asc())
    )
    inc_res = await db.execute(inc_stmt)
    incidents = inc_res.scalars().unique().all()

    segments: List[ViolenceSegment] = []
    all_identified_students_map = {}
    primary_image = None
    primary_video = None
    primary_incident_id = None
    max_confidence = 0.0

    for idx, inc in enumerate(incidents):
        if not primary_incident_id:
            primary_incident_id = inc.id
        if inc.confidence > max_confidence:
            max_confidence = inc.confidence

        det_event = next((e for e in inc.events if e.video_id == target_video.id), None)
        timestamp_sec = 0.0
        if det_event and det_event.timestamp and target_video.created_at:
            t_evt = det_event.timestamp.replace(tzinfo=None) if hasattr(det_event.timestamp, "tzinfo") and det_event.timestamp.tzinfo else det_event.timestamp
            t_vid = target_video.created_at.replace(tzinfo=None) if hasattr(target_video.created_at, "tzinfo") and target_video.created_at.tzinfo else target_video.created_at
            delta = (t_evt - t_vid).total_seconds()
            timestamp_sec = max(0.0, delta)

        if timestamp_sec == 0.0 and inc.explanation:
            t_match = re.search(r"altercation from\s*([0-9]+(?:\.[0-9]+)?)s", inc.explanation)
            if not t_match:
                t_match = re.search(r"altercation at\s*([0-9]+(?:\.[0-9]+)?)s", inc.explanation)
            if t_match:
                timestamp_sec = float(t_match.group(1))

        # Parse evidence media URLs
        seg_image = None
        seg_video = None
        for ev in inc.evidences:
            if not os.path.exists(ev.file_path) and not ev.file_path.startswith("http"):
                continue
            url = _clean_storage_url(ev.file_path)
            if ev.evidence_type == "video" and not seg_video:
                seg_video = url
            elif ev.evidence_type == "screenshot" and not seg_image:
                if ev.file_path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                    seg_image = url

        # On-demand frame extraction fallback if missing
        if not seg_image and target_video.file_path and os.path.exists(target_video.file_path):
            frame_filename = f"evidence_frame_{inc.id.hex}.jpg"
            frame_path = os.path.join(settings.STORAGE_DIR, "evidence", frame_filename)
            if not os.path.exists(frame_path):
                extract_evidence_frame(target_video.file_path, timestamp_sec, frame_path)
            if os.path.exists(frame_path):
                seg_image = _clean_storage_url(frame_path)
                db.add(Evidence(
                    id=uuid.uuid4(),
                    incident_id=inc.id,
                    evidence_type="screenshot",
                    file_path=frame_path,
                    timestamp=inc.timestamp
                ))

        # On-demand sub-clip generation fallback if missing
        if not seg_video and target_video.file_path and os.path.exists(target_video.file_path):
            clip_filename = f"clip_{inc.id.hex}.mp4"
            clip_path = os.path.join(settings.STORAGE_DIR, "evidence", clip_filename)
            if not os.path.exists(clip_path):
                generate_subclip(target_video.file_path, timestamp_sec, 6.0, clip_path)
            if os.path.exists(clip_path):
                seg_video = _clean_storage_url(clip_path)
                db.add(Evidence(
                    id=uuid.uuid4(),
                    incident_id=inc.id,
                    evidence_type="video",
                    file_path=clip_path,
                    timestamp=inc.timestamp
                ))

        if not primary_image and seg_image:
            primary_image = seg_image
        if not primary_video and seg_video:
            primary_video = seg_video

        # Parse involved students for this segment
        seg_students: List[InvolvedStudentCard] = []
        for ip in inc.persons:
            student = ip.student
            if not student and ip.student_id:
                s_res = await db.execute(select(Student).filter(Student.id == ip.student_id))
                student = s_res.scalars().first()

            if student:
                photo_url = await _get_student_profile_photo_url(db, student.id)
                card = InvolvedStudentCard(
                    student_id=student.id,
                    name=student.name,
                    roll_number=student.university_roll_number,
                    department=student.department,
                    programme=student.programme,
                    section=student.section,
                    class_name=f"{student.programme} {student.section}",
                    profile_photo_url=photo_url,
                    similarity_score=round(ip.confidence, 2),
                    confidence="high" if ip.confidence >= settings.RECOGNITION_HIGH_THRESHOLD else "medium",
                    track_id=str(det_event.track_id) if det_event and det_event.track_id else None,
                    event_id=str(det_event.id) if det_event else str(inc.id),
                    is_identified=True
                )
                seg_students.append(card)
                all_identified_students_map[student.id] = card

        # Extract multi-signal breakdown from explanation or defaults
        motion_score = 0.85
        proximity_score = 0.90
        clip_score = 0.75
        temporal_score = 0.80

        if inc.explanation:
            m_match = re.search(r"Motion dynamics:\s*([0-9]+(?:\.[0-9]+)?)", inc.explanation)
            if m_match:
                motion_score = float(m_match.group(1))
            p_match = re.search(r"Interaction proximity:\s*([0-9]+(?:\.[0-9]+)?)", inc.explanation)
            if p_match:
                proximity_score = float(p_match.group(1))
            c_match = re.search(r"CLIP score:\s*([0-9]+(?:\.[0-9]+)?)", inc.explanation)
            if c_match:
                clip_score = float(c_match.group(1))

        breakdown = ViolenceSignalBreakdown(
            motion_dynamics=min(1.0, motion_score),
            person_interaction=min(1.0, proximity_score),
            clip_similarity=min(1.0, clip_score),
            temporal_persistence=min(1.0, temporal_score)
        )

        start_t = max(0.0, timestamp_sec - 2.5)
        duration = 6.0
        if target_video.duration and target_video.duration > 0:
            end_t = min(target_video.duration, start_t + duration)
            if start_t >= end_t:
                start_t = max(0.0, end_t - min(6.0, target_video.duration))
            duration = max(0.1, round(end_t - start_t, 1))
        else:
            end_t = start_t + duration

        def _format_time_hms(s_val: float) -> str:
            secs = int(max(0.0, s_val))
            h = secs // 3600
            m = (secs % 3600) // 60
            s = secs % 60
            return f"{h:02d}:{m:02d}:{s:02d}"

        ts_display = f"{_format_time_hms(start_t)} - {_format_time_hms(end_t)}"

        # Resolve tracks appearing in this segment window
        seg_tracks: List[SegmentTrackInfo] = []
        associated_track_ids = set()
        for evt in inc.events:
            if evt.track_id:
                associated_track_ids.add(evt.track_id)
                
        trk_stmt = (
            select(Track)
            .options(selectinload(Track.detections))
            .filter(
                Track.video_id == target_video.id,
                Track.object_class == "person"
            )
        )
        trk_res = await db.execute(trk_stmt)
        all_video_tracks = trk_res.scalars().all()
        
        for trk in all_video_tracks:
            in_window = not (trk.end_time < start_t or trk.start_time > end_t)
            is_linked = trk.id in associated_track_ids
            if in_window or is_linked:
                window_dets = [d for d in trk.detections if (start_t <= d.timestamp_seconds <= end_t)]
                rep_det = window_dets[0] if window_dets else (trk.detections[0] if trk.detections else None)
                
                crop_url = _clean_storage_url(trk.key_frame_path) if trk.key_frame_path else None
                if not crop_url:
                    reid_stmt = (
                        select(PersonReid)
                        .filter(PersonReid.track_id == trk.id)
                        .order_by(PersonReid.timestamp_seconds.asc())
                    )
                    reid_res = await db.execute(reid_stmt)
                    reid_obj = reid_res.scalars().first()
                    if reid_obj and reid_obj.crop_path:
                        crop_url = _clean_storage_url(reid_obj.crop_path)
                
                if not crop_url and rep_det and target_video.file_path and os.path.exists(target_video.file_path):
                    try:
                        cap = cv2.VideoCapture(target_video.file_path)
                        cap.set(cv2.CAP_PROP_POS_FRAMES, int(rep_det.frame_number))
                        ret, f_img = cap.read()
                        cap.release()
                        if ret and f_img is not None:
                            h, w = f_img.shape[:2]
                            bx1, by1, bx2, by2 = rep_det.bounding_box
                            cx1 = max(0, min(w - 1, int(round(bx1))))
                            cy1 = max(0, min(h - 1, int(round(by1))))
                            cx2 = max(cx1 + 1, min(w, int(round(bx2))))
                            cy2 = max(cy1 + 1, min(h, int(round(by2))))
                            c_img = f_img[cy1:cy2, cx1:cx2]
                            if c_img.size > 0:
                                crops_dir = os.path.join(settings.STORAGE_DIR, "crops", str(target_video.id))
                                os.makedirs(crops_dir, exist_ok=True)
                                c_path = os.path.join(crops_dir, f"{trk.tracker_id}_{rep_det.frame_number}.jpg")
                                cv2.imwrite(c_path, c_img)
                                trk.key_frame_path = c_path
                                crop_url = _clean_storage_url(c_path)
                    except Exception as e:
                        logger.warning(f"Failed to generate on-demand crop for track {trk.id}: {str(e)}")
                        
                face_visible = False
                disk_crop_path = trk.key_frame_path
                if disk_crop_path and os.path.exists(disk_crop_path):
                    try:
                        from app.pipeline.face_engine import FaceEnrollmentEngine
                        fe = FaceEnrollmentEngine()
                        if fe.model is not None:
                            c_mat = cv2.imread(disk_crop_path)
                            if c_mat is not None:
                                ch, cw = c_mat.shape[:2]
                                upper_crop = c_mat[:max(20, int(ch * 0.55)), :] if ch > 30 else c_mat
                                faces = fe.model.get(upper_crop)
                                face_visible = len(faces) > 0
                    except Exception:
                        face_visible = False
                        
                matched_student = None
                id_confidence = "unidentified"
                sim_score = 0.0

                # 1. Check if track already matched to a student in seg_students
                already_in_seg = next((s for s in seg_students if s.track_id == str(trk.id) and s.is_identified), None)
                if already_in_seg and already_in_seg.student_id:
                    s_stmt = select(Student).filter(Student.id == already_in_seg.student_id)
                    s_res = await db.execute(s_stmt)
                    matched_student = s_res.scalars().first()
                    sim_score = already_in_seg.similarity_score
                    id_confidence = already_in_seg.confidence

                # 2. Check if track has identified_student_id in DB
                if not matched_student and trk.identified_student_id:
                    s_stmt = select(Student).filter(Student.id == trk.identified_student_id)
                    s_res = await db.execute(s_stmt)
                    matched_student = s_res.scalars().first()
                    rec_check = await db.execute(
                        select(StudentRecognitionEvent).filter(
                            StudentRecognitionEvent.track_id == trk.id,
                            StudentRecognitionEvent.student_id == trk.identified_student_id
                        )
                    )
                    rec_obj = rec_check.scalars().first()
                    if rec_obj:
                        sim_score = rec_obj.similarity_score
                        id_confidence = rec_obj.confidence or ("high" if sim_score >= settings.RECOGNITION_HIGH_THRESHOLD else "medium")
                    else:
                        sim_score = 0.85
                        id_confidence = "high"

                # 3. If not yet identified and crop exists, run StudentIdentifier
                if not matched_student and disk_crop_path and os.path.exists(disk_crop_path):
                    try:
                        from app.services.student_identifier import StudentIdentifier
                        identifier = StudentIdentifier()
                        match_res = await identifier.identify_face_in_crop(disk_crop_path)
                        if match_res and match_res.get("success") and match_res.get("student_id"):
                            found_id = match_res["student_id"]
                            sim_score = match_res["similarity_score"]
                            id_confidence = match_res["confidence"]
                            s_stmt = select(Student).filter(Student.id == found_id)
                            s_res = await db.execute(s_stmt)
                            matched_student = s_res.scalars().first()
                            if matched_student:
                                trk.identified_student_id = matched_student.id
                                rec_obj = StudentRecognitionEvent(
                                    id=uuid.uuid4(),
                                    track_id=trk.id,
                                    student_id=matched_student.id,
                                    video_id=target_video.id,
                                    timestamp=datetime.now(timezone.utc),
                                    similarity_score=sim_score,
                                    confidence=id_confidence,
                                    camera_id=str(resolved_camera.id) if resolved_camera else None
                                )
                                db.add(rec_obj)
                    except Exception as ie:
                        logger.warning(f"Student identification attempt failed for track {trk.id}: {str(ie)}")

                # 4. Construct student card (either identified or Unidentified Person)
                if matched_student:
                    photo_url = await _get_student_profile_photo_url(db, matched_student.id)
                    student_card = InvolvedStudentCard(
                        student_id=matched_student.id,
                        name=matched_student.name,
                        roll_number=matched_student.university_roll_number,
                        department=matched_student.department,
                        programme=matched_student.programme,
                        section=matched_student.section,
                        class_name=f"{matched_student.programme} {matched_student.section}",
                        profile_photo_url=photo_url,
                        similarity_score=round(sim_score, 2),
                        confidence=id_confidence,
                        track_id=str(trk.id),
                        event_id=str(det_event.id) if det_event else str(inc.id),
                        is_identified=True
                    )
                    if not any(s.student_id == matched_student.id for s in seg_students if s.student_id):
                        seg_students.append(student_card)
                    all_identified_students_map[matched_student.id] = student_card
                    
                    # Ensure IncidentPerson record in DB
                    ip_check = await db.execute(
                        select(IncidentPerson).filter(
                            IncidentPerson.incident_id == inc.id,
                            IncidentPerson.student_id == matched_student.id
                        )
                    )
                    if not ip_check.scalars().first():
                        db.add(IncidentPerson(
                            id=uuid.uuid4(),
                            incident_id=inc.id,
                            student_id=matched_student.id,
                            confidence=sim_score
                        ))
                else:
                    # Do NOT force every detected person to match a student.
                    student_card = InvolvedStudentCard(
                        student_id=None,
                        name="Unidentified Person",
                        roll_number="N/A",
                        department=None,
                        programme=None,
                        section=None,
                        class_name="Unknown Class",
                        profile_photo_url=None,
                        similarity_score=round(sim_score, 2) if sim_score > 0 else 0.0,
                        confidence="unidentified",
                        track_id=str(trk.id),
                        event_id=str(det_event.id) if det_event else str(inc.id),
                        is_identified=False
                    )
                    if not any(s.track_id == str(trk.id) for s in seg_students):
                        seg_students.append(student_card)

                seg_tracks.append(SegmentTrackInfo(
                    event_id=str(det_event.id) if det_event else str(inc.id),
                    track_id=str(trk.id),
                    tracker_id=trk.tracker_id,
                    frame_number=rep_det.frame_number if rep_det else 0,
                    timestamp_seconds=rep_det.timestamp_seconds if rep_det else round(start_t, 2),
                    bounding_box=rep_det.bounding_box if rep_det else [0.0, 0.0, 0.0, 0.0],
                    person_crop=crop_url,
                    confidence=rep_det.confidence if rep_det else 0.90,
                    face_visible=face_visible,
                    identified_student=student_card
                ))

        segments.append(ViolenceSegment(
            segment_id=str(inc.id),
            event_id=str(det_event.id) if det_event else str(inc.id),
            video_id=str(target_video.id),
            start_time=round(start_t, 1),
            end_time=round(end_t, 1),
            duration=round(duration, 1),
            timestamp_display=ts_display,
            confidence=round(inc.confidence, 2),
            severity="High" if inc.confidence >= 0.70 else "Medium",
            breakdown=breakdown,
            explanation=inc.explanation or f"Detected physical fight/altercation at {start_t:.1f}s.",
            evidence_image=seg_image,
            evidence_video=seg_video,
            students=seg_students,
            tracks=seg_tracks
        ))

    # Also resolve any identified students from the entire video if none were mapped directly to the segment
    if not all_identified_students_map:
        rec_stmt = (
            select(StudentRecognitionEvent)
            .filter(StudentRecognitionEvent.video_id == target_video.id)
            .order_by(StudentRecognitionEvent.similarity_score.desc())
        )
        rec_res = await db.execute(rec_stmt)
        for rec in rec_res.scalars().all():
            if rec.student_id not in all_identified_students_map:
                s_res = await db.execute(select(Student).filter(Student.id == rec.student_id))
                student = s_res.scalars().first()
                if student:
                    photo_url = await _get_student_profile_photo_url(db, student.id)
                    all_identified_students_map[student.id] = InvolvedStudentCard(
                        student_id=student.id,
                        name=student.name,
                        roll_number=student.university_roll_number,
                        department=student.department,
                        programme=student.programme,
                        section=student.section,
                        class_name=f"{student.programme} {student.section}",
                        profile_photo_url=photo_url,
                        similarity_score=rec.similarity_score,
                        confidence=rec.confidence,
                        track_id=str(rec.track_id)
                    )

    is_violence = len(segments) > 0
    status_label = "VIOLENCE_DETECTED" if is_violence else "NORMAL"
    verdict_text = (
        f"Detected {len(segments)} physical altercation / violence segment(s) ({max_confidence:.0%} Confidence)."
        if is_violence
        else "Normal campus activity verified. No violence or aggressive physical altercations detected."
    )

    cam = resolved_camera or target_video.camera
    return ViolenceAnalysisResponse(
        video_id=target_video.id,
        video_title=target_video.title or target_video.filename,
        camera_id=cam.id if cam else None,
        camera_name=cam.name if cam else "Surveillance Feed",
        camera_location=cam.location if cam else "Campus Ground",
        status=status_label,
        verdict=verdict_text,
        overall_confidence=round(max_confidence, 2) if is_violence else 0.0,
        total_segments=len(segments),
        segments=segments,
        primary_evidence_image=primary_image,
        primary_evidence_video=primary_video,
        identified_students=list(all_identified_students_map.values()),
        incident_id=primary_incident_id,
        analyzed_at=datetime.now(timezone.utc)
    )

@router.get("/status/{video_id}")
async def get_violence_video_status(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Poll processing progress and stage for a violence detection video job.
    """
    v_res = await db.execute(select(Video).filter(Video.id == video_id))
    video = v_res.scalars().first()
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Video {video_id} not found.")
    return {
        "video_id": str(video.id),
        "status": video.status,
        "stage": video.current_stage or "Ready",
        "progress": video.progress_percentage or 0,
        "error_message": video.error_message
    }

@router.get("/result/{video_id}", response_model=ViolenceAnalysisResponse)
async def get_violence_analysis_result(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Retrieve stored detection results, segments, confidence and evidence for a video.
    """
    v_res = await db.execute(
        select(Video)
        .options(selectinload(Video.camera))
        .filter(Video.id == video_id)
    )
    video = v_res.scalars().first()
    if not video:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Video {video_id} not found.")
    
    return await _compile_violence_dossier(db, video, video.camera)

@router.get("/history", response_model=List[dict])
async def list_violence_history(
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    List all recorded violence and physical fight incidents across camera feeds.
    """
    stmt = (
        select(Incident)
        .options(
            selectinload(Incident.persons).selectinload(IncidentPerson.student),
            selectinload(Incident.evidences),
            selectinload(Incident.camera)
        )
        .filter(Incident.incident_type.in_(["Fight", "Violence"]))
        .order_by(Incident.timestamp.desc())
    )
    res = await db.execute(stmt)
    incidents = res.scalars().all()

    output = []
    for inc in incidents:
        cam_name = inc.camera.name if inc.camera else "CCTV Camera"
        cam_loc = inc.camera.location if inc.camera else "Campus"
        students = [ip.student.name for ip in inc.persons if ip.student]
        
        output.append({
            "incident_id": str(inc.id),
            "timestamp": inc.timestamp.isoformat(),
            "camera": f"{cam_name} ({cam_loc})",
            "confidence": round(inc.confidence, 2),
            "students": students,
            "explanation": inc.explanation
        })
    return output

@router.post("/report", status_code=status.HTTP_201_CREATED)
async def generate_violence_report(
    payload: ViolenceReportRequest,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Generate an official forensic incident report directly from a violence analysis result.
    """
    inc = None
    det_event = None

    # 1. Resolve incident by event_id, incident_id, or video_id
    if payload.event_id:
        evt_stmt = select(DetectedEvent).filter(DetectedEvent.id == payload.event_id)
        evt_res = await db.execute(evt_stmt)
        det_event = evt_res.scalars().first()
        if det_event and det_event.incident_id:
            inc_stmt = (
                select(Incident)
                .options(
                    selectinload(Incident.persons).selectinload(IncidentPerson.student),
                    selectinload(Incident.evidences),
                    selectinload(Incident.camera),
                    selectinload(Incident.events)
                )
                .filter(Incident.id == det_event.incident_id)
            )
            inc_res = await db.execute(inc_stmt)
            inc = inc_res.scalars().first()

    if not inc and payload.incident_id:
        inc_stmt = (
            select(Incident)
            .options(
                selectinload(Incident.persons).selectinload(IncidentPerson.student),
                selectinload(Incident.evidences),
                selectinload(Incident.camera),
                selectinload(Incident.events)
            )
            .filter(Incident.id == payload.incident_id)
        )
        inc_res = await db.execute(inc_stmt)
        inc = inc_res.scalars().first()

    if not inc and payload.video_id:
        inc_stmt = (
            select(Incident)
            .join(DetectedEvent, Incident.id == DetectedEvent.incident_id)
            .options(
                selectinload(Incident.persons).selectinload(IncidentPerson.student),
                selectinload(Incident.evidences),
                selectinload(Incident.camera),
                selectinload(Incident.events)
            )
            .filter(
                DetectedEvent.video_id == payload.video_id,
                Incident.incident_type.in_(["Fight", "Violence"])
            )
            .order_by(Incident.timestamp.desc())
        )
        inc_res = await db.execute(inc_stmt)
        inc = inc_res.scalars().first()

    if not inc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Violence incident not found for provided identifiers (incident_id={payload.incident_id}, event_id={payload.event_id}, video_id={payload.video_id})."
        )

    if not det_event and inc.events:
        det_event = next((e for e in inc.events), None)

    # 2. Resolve Video Information
    video_id = det_event.video_id if det_event else payload.video_id
    target_video = None
    if video_id:
        v_res = await db.execute(select(Video).filter(Video.id == video_id))
        target_video = v_res.scalars().first()

    # 3. Resolve Evidence Items
    primary_image = None
    primary_video = None
    timeline_items = []
    for ev in inc.evidences:
        url = _clean_storage_url(ev.file_path)
        timeline_items.append({
            "type": ev.evidence_type,
            "url": url,
            "file_path": ev.file_path,
            "timestamp": ev.timestamp.isoformat()
        })
        if ev.evidence_type in ["screenshot", "image"] and not primary_image:
            primary_image = url
        elif ev.evidence_type == "video" and not primary_video:
            primary_video = url

    # 4. Resolve Involved Students (Photo, Name, Class, Roll Number, Identity Confidence)
    students_summary = []
    primary_student_id = None
    matched_student_ids = []
    for ip in inc.persons:
        student = ip.student
        if not student and ip.student_id:
            s_res = await db.execute(select(Student).filter(Student.id == ip.student_id))
            student = s_res.scalars().first()

        if student:
            if not primary_student_id:
                primary_student_id = student.id
            matched_student_ids.append(str(student.id))
            photo_url = await _get_student_profile_photo_url(db, student.id)
            cls_name = f"{student.programme or ''} {student.section or ''}".strip() or "Unknown Class"
            students_summary.append({
                "student_id": str(student.id),
                "name": student.name,
                "roll_number": student.university_roll_number or "N/A",
                "department": student.department or "Unknown Department",
                "class": cls_name,
                "class_name": cls_name,
                "identity_confidence": round(ip.confidence, 4),
                "confidence": "high" if ip.confidence >= settings.RECOGNITION_HIGH_THRESHOLD else "medium",
                "track_id": str(det_event.track_id) if det_event and det_event.track_id else None,
                "event_id": str(det_event.id) if det_event else str(inc.id),
                "profile_photo_url": photo_url
            })

    duration_seconds = 7.0
    start_timestamp_iso = inc.timestamp.isoformat()
    end_timestamp_dt = inc.timestamp + timedelta(seconds=duration_seconds)
    end_timestamp_iso = end_timestamp_dt.isoformat()
    person_track_ids = [str(e.track_id) for e in inc.events if e.track_id]

    # 5. Build Comprehensive Forensic Report Data
    cam_name = inc.camera.name if inc.camera else "Campus CCTV Camera"
    cam_loc = inc.camera.location if inc.camera else "Campus Area"
    report_title = payload.title or f"Forensic Violence Incident Report - {cam_name} ({cam_loc})"

    report_data = {
        "incident_id": str(inc.id),
        "event_id": str(det_event.id) if det_event else str(inc.id),
        "event_type": "VIOLENCE",
        "incident_type": "Violence",
        "title": report_title,
        "severity": "High" if inc.confidence >= 0.70 else "Medium",
        "confidence": round(inc.confidence, 4),
        "violence_confidence": round(inc.confidence, 4),
        "timestamp": start_timestamp_iso,
        "explanation": inc.explanation,
        "additional_notes": payload.additional_notes,
        "event_info": {
            "event_id": str(det_event.id) if det_event else str(inc.id),
            "event_type": "VIOLENCE",
            "start_timestamp": start_timestamp_iso,
            "end_timestamp": end_timestamp_iso,
            "duration_seconds": duration_seconds,
            "violence_confidence": round(inc.confidence, 4),
            "person_track_ids": person_track_ids,
            "matched_student_ids": matched_student_ids
        },
        "video_info": {
            "video_id": str(target_video.id) if target_video else (str(video_id) if video_id else None),
            "title": target_video.title if target_video else "Campus CCTV Footage",
            "filename": target_video.filename if target_video else (target_video.original_filename if target_video else "Campus_Camera_03.mp4"),
            "duration": target_video.duration if target_video else duration_seconds,
            "file_url": _clean_storage_url(target_video.file_path) if target_video else None
        },
        "camera": {
            "camera_id": str(inc.camera.id) if inc.camera else None,
            "name": cam_name,
            "location": cam_loc,
            "building": getattr(inc.camera, 'building', None) if inc.camera else None,
            "floor": getattr(inc.camera, 'floor', None) if inc.camera else None
        },
        "evidence": {
            "evidence_image": primary_image,
            "evidence_clip": primary_video,
            "image_url": primary_image,
            "video_url": primary_video,
            "items": timeline_items
        },
        "involved_students": students_summary,
        "timeline": timeline_items,
        "narrative_summary": inc.explanation or f"Physical altercation detected on {cam_name} involving {len(students_summary)} identified individual(s).",
        "generated_by": current_user.full_name or current_user.email,
        "generated_at": datetime.now(timezone.utc).isoformat()
    }

    report_obj = Report(
        id=uuid.uuid4(),
        title=report_title,
        incident_type="Violence",
        student_id=primary_student_id,
        created_at=datetime.now(timezone.utc),
        data=report_data
    )
    db.add(report_obj)
    await db.commit()
    await db.refresh(report_obj)

    return {
        "success": True,
        "report_id": str(report_obj.id),
        "title": report_obj.title,
        "created_at": report_obj.created_at.isoformat(),
        "incident_id": str(inc.id),
        "event_id": str(det_event.id) if det_event else str(inc.id),
        "data": report_data
    }
