import os
import re
import uuid
import time
import logging
import json
import numpy as np
from datetime import datetime, timezone, timedelta
from typing import Any, List, Optional, Dict, Tuple, Callable
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func, text
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
from app.pipeline.face_engine import FaceEnrollmentEngine
from starlette.concurrency import run_in_threadpool
import gc
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
from app.api.v1.videos import resolve_camera_id

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
    Validates file extension, size limit (500 MiB / 524,288,000 bytes), and video stream integrity (non-corrupt).
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
        max_size = settings.MAX_UPLOAD_SIZE_BYTES  # 500 MiB (524,288,000 bytes)
        with open(saved_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                total_size += len(chunk)
                if total_size > max_size:
                    buffer.close()
                    if os.path.exists(saved_path):
                        os.remove(saved_path)
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Video upload size exceeds 500 MiB limit ({settings.MAX_UPLOAD_SIZE_BYTES:,} bytes)."
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

    # Deduplication check on client retry: if an active record already exists for identical upload within 120s
    recent_cutoff = datetime.now(timezone.utc) - timedelta(seconds=120)
    dup_stmt = select(Video).filter(
        Video.uploaded_by == current_user.id,
        Video.original_filename == original_filename,
        Video.file_size == total_size,
        Video.created_at >= recent_cutoff,
        Video.status.in_(["uploaded", "processing", "completed"])
    ).order_by(Video.created_at.desc())
    dup_res = await db.execute(dup_stmt)
    existing_video = dup_res.scalars().first()
    if existing_video:
        logger.info(f"Duplicate upload detected on retry for video {original_filename}. Returning existing record {existing_video.id}.")
        if os.path.exists(saved_path):
            os.remove(saved_path)
        return ViolenceVideoUploadResponse(
            video_id=existing_video.id,
            title=existing_video.title,
            filename=existing_video.filename,
            original_filename=existing_video.original_filename,
            file_url=_clean_storage_url(existing_video.file_path),
            status=existing_video.status,
            duration=existing_video.duration,
            width=existing_video.width,
            height=existing_video.height,
            fps=existing_video.fps,
            codec=existing_video.codec,
            file_size=existing_video.file_size,
            uploaded_at=existing_video.created_at
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
        camera_id=resolve_camera_id(camera_id)
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

def _track_video_segments_sync(
    video_file_path: str,
    video_id: uuid.UUID,
    segments: List[Any],
    video_duration: Optional[float] = None,
    progress_callback: Optional[Callable[[int, int], None]] = None
) -> Tuple[Dict[int, Dict[str, Any]], float, float]:
    """
    Event-triggered person detection and tracking worker.
    Runs YOLOv8 and ByteTrack ONLY over the padded intervals around detected violence segments.
    Collects high-quality candidate person observations in bounded memory without executing
    expensive face detection during frame decoding.
    """
    yolo_detector = YOLOv8Detector()
    yolo_detector.target_classes = [0]  # Dedicated person detection for violence altercation tracking
    tracker = ByteTrackTracker()

    cap = cv2.VideoCapture(video_file_path)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    if fps <= 0:
        fps = 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = video_duration or (total_frames / fps if fps > 0 else 0.0)

    # 1. Cluster discrete violence segments into padded temporal intervals (-2.5s, +3.0s).
    # Avoid tracking huge non-violent time gaps (e.g. quiet lulls between altercations)
    sorted_segs = sorted(segments, key=lambda s: getattr(s, "start_time", 0.0))
    raw_intervals: List[Tuple[float, float]] = []
    for s in sorted_segs:
        st = max(0.0, float(getattr(s, "start_time", 0.0)) - 2.5)
        et = min(duration, float(getattr(s, "end_time", 0.0)) + 3.0) if duration > 0 else (float(getattr(s, "end_time", 0.0)) + 3.0)
        if not raw_intervals:
            raw_intervals.append((st, et))
        else:
            prev_st, prev_et = raw_intervals[-1]
            if st <= prev_et + 2.0:
                raw_intervals[-1] = (prev_st, max(prev_et, et))
            else:
                raw_intervals.append((st, et))

    frame_intervals: List[Tuple[int, int]] = []
    total_tracking_frames = 0
    for st, et in raw_intervals:
        f_start = max(0, int(st * fps))
        f_end = min(total_frames - 1, int(et * fps)) if total_frames > 0 else int(et * fps)
        if f_end >= f_start:
            frame_intervals.append((f_start, f_end))
            total_tracking_frames += (f_end - f_start + 1)

    if not frame_intervals:
        f_start = 0
        f_end = min(total_frames - 1, int(duration * fps)) if total_frames > 0 else 0
        frame_intervals = [(f_start, f_end)]
        total_tracking_frames = max(1, f_end - f_start + 1)

    all_video_tracks: Dict[int, Dict[str, Any]] = {}
    t_yolo_total = 0.0
    t_bytetrack_total = 0.0

    from app.tasks.video_tasks import is_video_cancelled
    frames_processed_so_far = 0
    is_cancelled = False

    for f_start, f_end in frame_intervals:
        if is_cancelled:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_start)
        current_frame_idx = f_start
        while current_frame_idx <= f_end:
            if current_frame_idx % 15 == 0 and is_video_cancelled(video_id):
                logger.info(f"[VIOLENCE PIPELINE] Video {video_id} cancelled during tracking. Halting.")
                is_cancelled = True
                break

            if progress_callback and frames_processed_so_far % 15 == 0:
                try:
                    progress_callback(frames_processed_so_far, total_tracking_frames)
                except Exception:
                    pass

            ret, frame = cap.read()
            if not ret or frame is None:
                break

            frames_processed_so_far += 1
            t_sec = current_frame_idx / fps

            t_track_start = time.time()
            track_result = tracker.track_frame(yolo_detector, frame, persist=True)
            step_duration = time.time() - t_track_start

            # Measure YOLO detection time vs ByteTrack tracking time
            if track_result is not None and hasattr(track_result, "speed") and isinstance(track_result.speed, dict):
                yolo_ms = float(track_result.speed.get("inference", 0.0)) + float(track_result.speed.get("preprocess", 0.0))
                yolo_sec = yolo_ms / 1000.0
                bt_sec = max(0.0, step_duration - yolo_sec)
                t_yolo_total += yolo_sec
                t_bytetrack_total += bt_sec
            else:
                t_yolo_total += (step_duration * 0.70)
                t_bytetrack_total += (step_duration * 0.30)

            if track_result is not None and track_result.boxes is not None:
                boxes = track_result.boxes
                for box in boxes:
                    cls_id = int(box.cls[0].item())
                    if cls_id != 0:  # Class 0: person
                        continue

                    conf = float(box.conf[0].item())
                    xyxy = box.xyxy[0].cpu().numpy().tolist()
                    tracker_id = int(box.id[0].item()) if box.id is not None else current_frame_idx

                    h, w = frame.shape[:2]
                    x1, y1, x2, y2 = map(int, xyxy)
                    x1, y1 = max(0, x1), max(0, y1)
                    x2, y2 = min(w, x2), min(h, y2)
                    crop_w = x2 - x1
                    crop_h = y2 - y1

                    if tracker_id not in all_video_tracks:
                        all_video_tracks[tracker_id] = {
                            "detections": [],
                            "candidate_face_crops": [],
                            "best_crop_path": None,
                            "best_face_score": 0.0,
                            "best_conf": 0.0,
                            "start_time": t_sec,
                            "end_time": t_sec,
                            "_candidate_crops": []
                        }

                    trk_entry = all_video_tracks[tracker_id]
                    trk_entry["end_time"] = t_sec
                    trk_entry["detections"].append({
                        "frame_number": current_frame_idx,
                        "timestamp_seconds": round(t_sec, 2),
                        "bounding_box": [round(c, 1) for c in xyxy],
                        "confidence": round(conf, 4)
                    })

                    # Context-padded observation selection with time-spread binning
                    if crop_w >= 30 and crop_h >= 40:
                        # 10-12% contextual padding with safe frame-boundary clamping
                        pad_x = int(crop_w * 0.12)
                        pad_y = int(crop_h * 0.12)
                        px1 = max(0, x1 - pad_x)
                        py1 = max(0, y1 - pad_y)
                        px2 = min(w, x2 + pad_x)
                        py2 = min(h, y2 + pad_y)

                        padded_crop = frame[py1:py2, px1:px2]
                        pch, pcw = padded_crop.shape[:2]

                        # Measurable upper-body / head-region sharpness (Laplacian variance)
                        head_h = max(20, int(0.55 * pch))
                        head_crop = padded_crop[0:head_h, :]
                        gray_head = cv2.cvtColor(head_crop, cv2.COLOR_BGR2GRAY)
                        sharpness = float(cv2.Laplacian(gray_head, cv2.CV_64F).var())

                        aspect = crop_h / max(1, crop_w)
                        aspect_weight = 1.2 if (1.4 <= aspect <= 3.2) else 0.8
                        # Candidate score combines upper-body sharpness, aspect ratio, square-root size, and confidence
                        cand_score = float(np.log1p(max(0.0, sharpness)) * aspect_weight * np.sqrt(crop_w * crop_h) * conf)

                        cand_item = {
                            "crop": padded_crop.copy(),
                            "frame_idx": current_frame_idx,
                            "quality": cand_score,
                            "sharpness": sharpness,
                            "conf": conf,
                            "timestamp": t_sec
                        }

                        cands = trk_entry["_candidate_crops"]
                        min_gap = max(6, int(fps * 0.25))  # Enforce temporal separation across candidates

                        if len(cands) < 4:
                            too_close = False
                            for existing in cands:
                                if abs(existing["frame_idx"] - current_frame_idx) < min_gap:
                                    too_close = True
                                    if cand_score > existing["quality"]:
                                        existing.update(cand_item)
                                    break
                            if not too_close:
                                cands.append(cand_item)
                        else:
                            replaced = False
                            for existing in cands:
                                if abs(existing["frame_idx"] - current_frame_idx) < min_gap:
                                    if cand_score > existing["quality"]:
                                        existing.update(cand_item)
                                        replaced = True
                                    break
                            if not replaced:
                                min_cand_idx = min(range(len(cands)), key=lambda i: cands[i]["quality"])
                                if cand_score > cands[min_cand_idx]["quality"] * 1.25:
                                    cands[min_cand_idx] = cand_item

            current_frame_idx += 1

    cap.release()
    return all_video_tracks, t_yolo_total, t_bytetrack_total


def _detect_faces_on_candidates_sync(
    crop_dir: str,
    valid_tracks: Dict[int, Dict[str, Any]]
) -> Tuple[Dict[int, Dict[str, Any]], float, int]:
    """
    Event-triggered face detection: runs InsightFace SCRFD ONLY on selected high-quality
    candidate person observations from violence intervals, rather than inspecting
    unrelated frames or repetitively checking blurry turned-away crops.
    """
    face_engine = FaceEnrollmentEngine()
    t_start = time.time()
    call_count = 0
    os.makedirs(crop_dir, exist_ok=True)

    for trk_id, trk_entry in valid_tracks.items():
        candidates = trk_entry.pop("_candidate_crops", [])
        # Sort candidates descending by quality
        candidates.sort(key=lambda c: c.get("quality", 0.0), reverse=True)

        cand_face_list = []
        best_face_score = 0.0
        best_crop_path = None

        for cand in candidates[:3]:  # At most top 3 candidate observations per track
            crop = cand.get("crop")
            frame_idx = cand.get("frame_idx")
            if crop is None or crop.size == 0 or face_engine.model is None:
                continue

            ch, cw = crop.shape[:2]
            # Focus on upper body (head region) for standing human
            detect_crop = crop[0:int(0.60 * ch), :] if (ch / max(1, cw) > 1.2) else crop

            call_count += 1
            faces = face_engine.model.get(detect_crop if detect_crop.size > 0 else crop)
            if not faces:
                continue

            valid_faces = []
            for f in faces:
                if f.det_score < 0.45:
                    continue
                fx1, fy1, fx2, fy2 = map(int, f.bbox)
                fw, fh = fx2 - fx1, fy2 - fy1
                if fw < 20 or fh < 20:
                    continue
                fcx = (fx1 + fx2) / 2.0
                fcy = (fy1 + fy2) / 2.0
                if fcy > 0.65 * ch:
                    continue
                blur_score = face_engine.calculate_blur_score(crop, [fx1, fy1, fx2, fy2])
                if blur_score < 10.0:
                    continue
                dist_from_center = abs(fcx - (cw / 2.0)) / max(1.0, cw)
                valid_faces.append((f, dist_from_center, blur_score))

            if valid_faces:
                best_f = min(valid_faces, key=lambda item: (item[1] if item[1] > 0.35 else 0.0, -item[0].det_score))[0]
                fx1, fy1, fx2, fy2 = map(int, best_f.bbox)
                pad_w = int((fx2 - fx1) * 0.25)
                pad_h = int((fy2 - fy1) * 0.25)
                face_x1 = max(0, fx1 - pad_w)
                face_y1 = max(0, fy1 - pad_h)
                face_x2 = min(cw, fx2 + pad_w)
                face_y2 = min(ch, fy2 + pad_h)
                face_crop = crop[face_y1:face_y2, face_x1:face_x2] if (face_x2 > face_x1 and face_y2 > face_y1) else crop

                cand_filename = f"crop_trk_{trk_id}_face_f{frame_idx}.jpg"
                cand_path = os.path.join(crop_dir, cand_filename)
                cv2.imwrite(cand_path, face_crop)

                emb_vec = None
                raw_emb = getattr(best_f, "normed_embedding", None)
                if raw_emb is None:
                    raw_emb = getattr(best_f, "embedding", None)
                if raw_emb is not None:
                    arr_e = np.array(raw_emb, dtype=np.float32)
                    if arr_e.shape == (512,) and np.all(np.isfinite(arr_e)):
                        e_norm = np.linalg.norm(arr_e)
                        if e_norm > 0:
                            emb_vec = (arr_e / e_norm).tolist()

                cand_entry = {
                    "det_score": float(best_f.det_score),
                    "path": cand_path,
                    "frame": frame_idx,
                    "embedding": emb_vec
                }
                cand_face_list.append(cand_entry)

                if float(best_f.det_score) > best_face_score:
                    best_face_score = float(best_f.det_score)
                    best_crop_path = cand_path

                # Observation reuse / early exit: If this face observation has high detector confidence (>= 0.65),
                # we have an optimal face observation for this track; stop evaluating further candidates.
                if float(best_f.det_score) >= 0.65:
                    break

        trk_entry["candidate_face_crops"] = cand_face_list
        trk_entry["best_face_score"] = best_face_score

        # If no face was found, save the highest quality body crop as fallback thumbnail
        if not best_crop_path and candidates:
            best_cand = candidates[0]
            fb_filename = f"crop_trk_{trk_id}_body_f{best_cand['frame_idx']}.jpg"
            fb_path = os.path.join(crop_dir, fb_filename)
            cv2.imwrite(fb_path, best_cand["crop"])
            best_crop_path = fb_path

        trk_entry["best_crop_path"] = best_crop_path

    t_elapsed = time.time() - t_start
    return valid_tracks, t_elapsed, call_count

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
    if file and hasattr(file, "filename") and file.filename:
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
            max_size = settings.MAX_UPLOAD_SIZE_BYTES  # 500 MiB (524,288,000 bytes)
            with open(saved_path, "wb") as buffer:
                while chunk := await file.read(1024 * 1024):
                    total_size += len(chunk)
                    if total_size > max_size:
                        buffer.close()
                        if os.path.exists(saved_path):
                            os.remove(saved_path)
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Video file exceeds maximum 500 MiB size limit ({settings.MAX_UPLOAD_SIZE_BYTES:,} bytes)."
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
            camera_id=resolve_camera_id(camera_id)
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
        valid_cam = resolve_camera_id(camera_id)
        if valid_cam and not target_video.camera_id:
            target_video.camera_id = valid_cam
            await db.commit()

    # 2. Resolve Camera
    resolved_camera: Optional[Camera] = None
    target_cam_id = resolve_camera_id(target_video.camera_id) or resolve_camera_id(camera_id)
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
    t_face_detect_total = 0.0
    t_arcface_total = 0.0
    t_evidence_total = 0.0
    t_db_total = 0.0
    face_call_count = 0

    now_utc = datetime.now(timezone.utc)
    target_video.status = "processing"
    target_video.current_stage = "X3D-M Temporal Violence Detection"
    target_video.progress_percentage = 30
    target_video.processing_started_at = now_utc
    await db.commit()
    run_id = now_utc.strftime("%Y%m%d%H%M%S")

    db_path = os.path.join(settings.STORAGE_DIR, "cctv.db")
    vid_uuid_str = str(target_video.id)
    last_reported_pct = [30]

    def _update_sync_progress(pct: int, stage_desc: str):
        try:
            import sqlite3
            with sqlite3.connect(db_path, timeout=5.0) as sconn:
                sc = sconn.cursor()
                sc.execute(
                    "UPDATE videos SET progress_percentage = ?, current_stage = ? WHERE id = ?",
                    (pct, stage_desc, vid_uuid_str)
                )
                sconn.commit()
        except Exception as p_err:
            logger.debug(f"[Progress Hook] Ignored DB update error: {p_err}")

    def _x3d_progress_hook(done_w: int, total_w: int):
        if total_w <= 0:
            return
        pct = 30 + int((done_w / total_w) * 28)
        if pct >= last_reported_pct[0] + 3 or done_w == total_w:
            last_reported_pct[0] = pct
            _update_sync_progress(pct, f"X3D-M Temporal Violence Detection ({done_w}/{total_w} windows)")

    def _track_progress_hook(done_f: int, total_f: int):
        if total_f <= 0:
            return
        pct = 60 + int((done_f / total_f) * 20)
        if pct >= last_reported_pct[0] + 1 or done_f == total_f:
            last_reported_pct[0] = pct
            _update_sync_progress(pct, f"Processing Violence Segments ({done_f}/{total_f} frames)")

    try:
        # Step 1: Run Pretrained X3D-M Video Temporal Model
        t_x3d_load_start = time.time()
        x3d_detector = X3DViolenceDetector()
        t_x3d_load = time.time() - t_x3d_load_start

        x3d_res = await run_in_threadpool(
            x3d_detector.detect_violence,
            target_video.file_path,
            window_duration_sec=2.0,
            stride_sec=1.0,
            threshold=0.4,
            context_margin_sec=1.0,
            batch_size=16,
            progress_callback=_x3d_progress_hook
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
        # Clean up any prior violence analysis records for this video to ensure idempotency on re-analysis
        vid_str = str(target_video.id)
        det_events_res = await db.execute(
            select(DetectedEvent.incident_id).filter(
                DetectedEvent.video_id == target_video.id,
                DetectedEvent.incident_id.isnot(None)
            ).distinct()
        )
        cand_incident_ids = [r[0] for r in det_events_res.fetchall()]
        for inc_id in cand_incident_ids:
            other_refs = (await db.execute(
                select(func.count(DetectedEvent.id)).filter(
                    DetectedEvent.incident_id == inc_id,
                    DetectedEvent.video_id != target_video.id
                )
            )).scalar() or 0
            if other_refs == 0:
                i_str = str(inc_id)
                await db.execute(text("DELETE FROM evidences WHERE incident_id = :iid").bindparams(iid=i_str))
                await db.execute(text("DELETE FROM incident_persons WHERE incident_id = :iid").bindparams(iid=i_str))
                await db.execute(text("DELETE FROM incidents WHERE id = :iid").bindparams(iid=i_str))

        await db.execute(
            text("DELETE FROM event_tracks WHERE track_id IN (SELECT id FROM tracks WHERE video_id = :vid)").bindparams(vid=vid_str)
        )
        await db.execute(
            text("DELETE FROM student_recognition_events WHERE video_id = :vid").bindparams(vid=vid_str)
        )
        await db.execute(
            text("DELETE FROM person_reids WHERE video_id = :vid").bindparams(vid=vid_str)
        )
        await db.execute(
            text("DELETE FROM detections WHERE track_id IN (SELECT id FROM tracks WHERE video_id = :vid)").bindparams(vid=vid_str)
        )
        await db.execute(
            text("DELETE FROM tracks WHERE video_id = :vid").bindparams(vid=vid_str)
        )
        await db.execute(
            text("DELETE FROM detected_events WHERE video_id = :vid").bindparams(vid=vid_str)
        )
        await db.commit()

        target_video.current_stage = "Processing Violence Segments (YOLOv8 & ByteTrack)"
        target_video.progress_percentage = 60
        await db.commit()

        video_duration = target_video.duration or 0.0

        # Run frame tracking & crop extraction in threadpool worker so FastAPI event loop remains unblocked
        all_video_tracks, t_yolo_step, t_bt_step = await run_in_threadpool(
            _track_video_segments_sync,
            target_video.file_path,
            target_video.id,
            x3d_res.segments,
            video_duration,
            _track_progress_hook
        )
        t_yolo_total += t_yolo_step
        t_bytetrack_total += t_bt_step

        _update_sync_progress(78, "Event-Triggered Face Detection (InsightFace)")

        from app.tasks.video_tasks import is_video_cancelled
        if is_video_cancelled(target_video.id):
            logger.info(f"[VIOLENCE PIPELINE] Video {target_video.id} was cancelled during frame tracking. Halting.")
            return None

        # Step 2b: Filter out transient micro-tracks (< 4 detections or < 0.20s duration),
        # but ALWAYS keep tracks that have candidate observations!
        valid_video_tracks = {
            tid: trk for tid, trk in all_video_tracks.items()
            if (len(trk["detections"]) >= 4 and (trk["end_time"] - trk["start_time"]) >= 0.20)
            or len(trk.get("_candidate_crops", [])) > 0
        }
        if not valid_video_tracks:
            valid_video_tracks = all_video_tracks

        # Step 2c: Event-Triggered Face Detection on Curated Track Observations
        crop_dir = os.path.join(settings.STORAGE_DIR, "crops", str(target_video.id))
        valid_video_tracks, t_face_detect_step, step_face_calls = await run_in_threadpool(
            _detect_faces_on_candidates_sync,
            crop_dir,
            valid_video_tracks
        )
        t_face_detect_total += t_face_detect_step
        face_call_count += step_face_calls

        _update_sync_progress(86, "Biometric Student Identification (ArcFace)")

        # Step 2d: Biometric Student Identification on Candidate Crops
        t_arc_start = time.time()
        track_identity_cache: Dict[int, Optional[Dict[str, Any]]] = {}
        incident_student_observations: Dict[uuid.UUID, Dict[str, Any]] = {}

        # Pre-load enrolled student embeddings from database for fast and robust vector comparison
        enrolled_db_embeddings: List[Tuple[uuid.UUID, np.ndarray]] = []
        try:
            db_emb_res = await db.execute(text("SELECT student_id, embedding FROM student_face_embeddings"))
            for sid_val, raw_emb in db_emb_res.fetchall():
                if not raw_emb:
                    continue
                v_arr = np.array(json.loads(raw_emb) if isinstance(raw_emb, str) else raw_emb, dtype=np.float32)
                v_norm = np.linalg.norm(v_arr)
                if v_norm > 0:
                    v_arr = v_arr / v_norm
                enrolled_db_embeddings.append((uuid.UUID(str(sid_val)), v_arr))
        except Exception as lde:
            logger.warning(f"[VIOLENCE PIPELINE] Could not preload enrolled embeddings from DB: {lde}")

        # Preload Student records to eliminate redundant SELECT queries during candidate evaluation
        all_std_res = await db.execute(select(Student))
        enrolled_students_map: Dict[uuid.UUID, Student] = {s.id: s for s in all_std_res.scalars().all()}
        db_sids = [sid for sid, _ in enrolled_db_embeddings]
        db_matrix = np.stack([vec for _, vec in enrolled_db_embeddings]) if enrolled_db_embeddings else None
        from app.services.student_identifier import StudentIdentifier
        identifier = StudentIdentifier()

        for trk_id, trk_data in valid_video_tracks.items():
            candidate_list = trk_data.get("candidate_face_crops", [])
            student_obs_for_track: Dict[uuid.UUID, List[Dict[str, Any]]] = {}

            if not candidate_list and trk_data.get("best_crop_path") and os.path.exists(trk_data["best_crop_path"]):
                candidate_list = [{"path": trk_data["best_crop_path"], "embedding": None}]

            for cand in candidate_list:
                cand_path = cand.get("path")
                cand_emb = cand.get("embedding")
                sim = 0.0
                best_sid = None
                second_sim = 0.0
                second_sid = None

                # 1. Vectorized cosine similarity matching using precomputed normalized embedding
                if cand_emb is not None and isinstance(cand_emb, list) and len(cand_emb) == 512 and db_matrix is not None and len(db_sids) > 0:
                    emb_arr = np.array(cand_emb, dtype=np.float32)
                    if np.all(np.isfinite(emb_arr)):
                        e_norm = np.linalg.norm(emb_arr)
                        if e_norm > 0:
                            emb_arr = emb_arr / e_norm
                            sims = np.dot(db_matrix, emb_arr)
                    if len(sims) == 1:
                        sim = float(sims[0])
                        best_sid = db_sids[0]
                    elif len(sims) > 1:
                        top2_idx = np.argpartition(-sims, 1)[:2]
                        top2_idx = top2_idx[np.argsort(-sims[top2_idx])]
                        sim = float(sims[top2_idx[0]])
                        best_sid = db_sids[top2_idx[0]]
                        second_sim = float(sims[top2_idx[1]])
                        second_sid = db_sids[top2_idx[1]]
                elif cand_path and os.path.exists(cand_path):
                    # 2. Fallback to StudentIdentifier if no precomputed embedding
                    try:
                        match_res = await identifier.identify_face_in_crop(cand_path)
                        if match_res and match_res.get("success") and match_res.get("student_id"):
                            m_sim = match_res.get("similarity_score", 0.0)
                            if m_sim > sim:
                                sim = m_sim
                                best_sid = match_res["student_id"]
                    except Exception as fe:
                        logger.warning(f"[VIOLENCE PIPELINE] StudentIdentifier fallback error for track {trk_id}: {fe}")

                # Reject ambiguous or low-quality faces (below threshold or overlapping top candidates)
                if best_sid and sim >= settings.RECOGNITION_MEDIUM_THRESHOLD:
                    if second_sid and second_sid != best_sid and second_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD:
                        if (sim - second_sim) < 0.05:
                            logger.info(f"[VIOLENCE PIPELINE] Ambiguous candidate rejected on track {trk_id}: {best_sid} ({sim:.3f}) vs {second_sid} ({second_sim:.3f})")
                            continue

                    student_obj = enrolled_students_map.get(best_sid)
                    if not student_obj:
                        s_stmt = select(Student).filter(Student.id == best_sid)
                        s_res = await db.execute(s_stmt)
                        student_obj = s_res.scalars().first()
                        if student_obj:
                            enrolled_students_map[best_sid] = student_obj
                    if student_obj:
                        obs_entry = {
                            "student": student_obj,
                            "similarity_score": sim,
                            "confidence": "high" if sim >= settings.RECOGNITION_HIGH_THRESHOLD else "medium",
                            "matched_crop_path": cand_path,
                            "frame": cand.get("frame")
                        }
                        student_obs_for_track.setdefault(best_sid, []).append(obs_entry)

                        if best_sid not in incident_student_observations or sim > incident_student_observations[best_sid]["similarity_score"]:
                            incident_student_observations[best_sid] = {
                                **obs_entry,
                                "track_id": trk_id
                            }

            trk_data["_student_obs"] = student_obs_for_track

            # Determine unambiguous primary identity for this track
            if student_obs_for_track:
                # Rank candidates by observation count and peak similarity
                best_sid = max(
                    student_obs_for_track.keys(),
                    key=lambda sid: (
                        len(student_obs_for_track[sid]),
                        max(o["similarity_score"] for o in student_obs_for_track[sid])
                    )
                )
                peak_obs = max(student_obs_for_track[best_sid], key=lambda o: o["similarity_score"])
                track_identity_cache[trk_id] = {
                    "student": peak_obs["student"],
                    "similarity_score": peak_obs["similarity_score"],
                    "confidence": peak_obs["confidence"],
                    "matched_crop_path": peak_obs["matched_crop_path"]
                }
                # Always ensure key frame crop path corresponds strictly to this primary student
                if peak_obs.get("matched_crop_path"):
                    trk_data["best_crop_path"] = peak_obs["matched_crop_path"]
            else:
                track_identity_cache[trk_id] = None

        # Multi-track Identity Deduplication:
        # A single physical person cannot simultaneously occupy two distinct concurrent tracks in the same altercation.
        # If multiple tracks claim the same student, award the identity to the track with stronger evidence
        # (higher observation count, then higher peak similarity). For the other track, fall back to its next best candidate or mark unidentified.
        claimed_students: Dict[uuid.UUID, int] = {}
        sorted_track_ids = sorted(
            [tid for tid, info in track_identity_cache.items() if info is not None],
            key=lambda tid: (
                len(valid_video_tracks[tid].get("_student_obs", {}).get(track_identity_cache[tid]["student"].id, [])),
                track_identity_cache[tid]["similarity_score"]
            ),
            reverse=True
        )
        for tid in sorted_track_ids:
            cand_info = track_identity_cache[tid]
            cand_sid = cand_info["student"].id
            if cand_sid in claimed_students:
                # Already claimed by a stronger track in this altercation.
                alt_obs_dict = valid_video_tracks[tid].get("_student_obs", {})
                alt_candidates = [
                    (sid, obs_list) for sid, obs_list in alt_obs_dict.items()
                    if sid not in claimed_students
                ]
                if alt_candidates:
                    alt_sid, alt_obs_list = max(
                        alt_candidates,
                        key=lambda item: (len(item[1]), max(o["similarity_score"] for o in item[1]))
                    )
                    peak_alt = max(alt_obs_list, key=lambda o: o["similarity_score"])
                    track_identity_cache[tid] = {
                        "student": peak_alt["student"],
                        "similarity_score": peak_alt["similarity_score"],
                        "confidence": peak_alt["confidence"],
                        "matched_crop_path": peak_alt["matched_crop_path"]
                    }
                    if peak_alt.get("matched_crop_path"):
                        valid_video_tracks[tid]["best_crop_path"] = peak_alt["matched_crop_path"]
                    claimed_students[alt_sid] = tid
                else:
                    logger.info(f"[VIOLENCE PIPELINE] Track {tid} duplicate identity {cand_sid} cleanly reassigned to Unidentified Person")
                    track_identity_cache[tid] = None
            else:
                claimed_students[cand_sid] = tid

        t_arcface_total += (time.time() - t_arc_start)

        if is_video_cancelled(target_video.id):
            logger.info(f"[VIOLENCE PIPELINE] Video {target_video.id} was cancelled before persistence. Rolling back.")
            await db.rollback()
            return None

        v_check = await db.execute(select(Video.id).filter(Video.id == target_video.id))
        if not v_check.scalar():
            logger.info(f"[VIOLENCE PIPELINE] Video {target_video.id} no longer exists in DB. Rolling back.")
            await db.rollback()
            return None

        # Step 2d: Evidence Generation and Persistence for Each Segment
        persisted_tracks_map: Dict[int, uuid.UUID] = {}
        _update_sync_progress(90, "Evidence Extraction & Persistence")

        for seg_idx, seg in enumerate(x3d_res.segments):
            seg_start_sec = max(0.0, seg.start_time)
            seg_end_sec = min(video_duration, seg.end_time) if video_duration > 0 else seg.end_time

            # Evidence Generation
            t_ev_start = time.time()
            os.makedirs(os.path.join(settings.STORAGE_DIR, "evidence"), exist_ok=True)
            mid_sec = (seg_start_sec + seg_end_sec) / 2.0
            frame_filename = f"evidence_frame_x3d_{target_video.id.hex[:8]}_seg{seg_idx}.jpg"
            frame_path = os.path.join(settings.STORAGE_DIR, "evidence", frame_filename)
            await run_in_threadpool(extract_evidence_frame, target_video.file_path, mid_sec, frame_path)

            clip_filename = f"clip_x3d_{target_video.id.hex[:8]}_seg{seg_idx}.mp4"
            clip_path = os.path.join(settings.STORAGE_DIR, "evidence", clip_filename)
            await run_in_threadpool(generate_subclip, target_video.file_path, seg_start_sec, seg.duration, clip_path)
            t_evidence_total += (time.time() - t_ev_start)

            # Database Persistence
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

            # Associate tracks active within this segment window (with 2.5s tolerance)
            seg_tracks = {
                tid: trk for tid, trk in valid_video_tracks.items()
                if not (trk["end_time"] < (seg_start_sec - 2.5) or trk["start_time"] > (seg_end_sec + 2.5))
            }
            if not seg_tracks:
                seg_tracks = {
                    tid: trk for tid, trk in valid_video_tracks.items()
                    if tid in track_identity_cache and track_identity_cache[tid] is not None
                }

            added_incident_students = set()
            for trk_id, trk_data in seg_tracks.items():
                primary_info = track_identity_cache.get(trk_id)
                primary_sid = primary_info["student"].id if primary_info else None

                if trk_id not in persisted_tracks_map:
                    t_uuid = uuid.uuid4()
                    persisted_tracks_map[trk_id] = t_uuid

                    db_track = Track(
                        id=t_uuid,
                        video_id=target_video.id,
                        object_class="person",
                        tracker_id=trk_id,
                        start_time=trk_data["start_time"],
                        end_time=trk_data["end_time"],
                        identified_student_id=primary_sid,
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

                # If track has a confirmed primary identity, associate with incident
                if primary_info:
                    matched_sid = primary_info["student"].id
                    if matched_sid not in added_incident_students:
                        added_incident_students.add(matched_sid)
                        db.add(IncidentPerson(
                            id=uuid.uuid4(),
                            incident_id=incident_id,
                            student_id=matched_sid,
                            confidence=primary_info["similarity_score"]
                        ))

                    db.add(StudentRecognitionEvent(
                        id=uuid.uuid4(),
                        track_id=persisted_tracks_map[trk_id],
                        student_id=matched_sid,
                        video_id=target_video.id,
                        timestamp=datetime.now(timezone.utc),
                        similarity_score=primary_info["similarity_score"],
                        confidence=primary_info["confidence"],
                        camera_id=str(resolved_camera.id) if resolved_camera else None
                    ))

            # Also associate all confirmed students observed during the altercation interaction
            for obs_sid, obs_info in incident_student_observations.items():
                if obs_sid not in added_incident_students:
                    added_incident_students.add(obs_sid)
                    db.add(IncidentPerson(
                        id=uuid.uuid4(),
                        incident_id=incident_id,
                        student_id=obs_sid,
                        confidence=obs_info["similarity_score"]
                    ))
                    obs_trk_id = obs_info.get("track_id")
                    t_target_uuid = persisted_tracks_map.get(obs_trk_id)
                    if t_target_uuid:
                        db.add(StudentRecognitionEvent(
                            id=uuid.uuid4(),
                            track_id=t_target_uuid,
                            student_id=obs_sid,
                            video_id=target_video.id,
                            timestamp=datetime.now(timezone.utc),
                            similarity_score=obs_info["similarity_score"],
                            confidence=obs_info["confidence"],
                            camera_id=str(resolved_camera.id) if resolved_camera else None
                        ))

            await db.commit()
            t_db_total += (time.time() - t_db_start)

        # Cleanup memory
        gc.collect()

        # Step 3: Complete timing instrumentation
        t_total = time.time() - t_total_start
        logger.info(f"[X3D] Violence Detection: {x3d_res.timings.get('total_x3d_sec', 0.0):.3f} sec")
        logger.info(f"[YOLO] Person Detection: {t_yolo_total:.3f} sec")
        logger.info(f"[ByteTrack] Tracking: {t_bytetrack_total:.3f} sec")
        logger.info(f"[InsightFace] Face Detection: {t_face_detect_total:.3f} sec (Calls: {face_call_count})")
        logger.info(f"[ArcFace] Student Identification: {t_arcface_total:.3f} sec")
        logger.info(f"[Evidence] Generation: {t_evidence_total:.3f} sec")
        logger.info(f"[DB] Persistence: {t_db_total:.3f} sec")
        logger.info(f"[TOTAL End-to-End]: {t_total:.3f} sec")

        target_video.status = "completed"
        target_video.current_stage = "Violence Analysis Completed"
        target_video.progress_percentage = 100
        await db.commit()

        # Dispatch consolidated violence alert if segments were detected
        if x3d_res.segments:
            try:
                from app.services.alert_dispatcher import AlertDispatcher
                earliest_t = min(s.start_time for s in x3d_res.segments) if x3d_res.segments else 0.0
                mins = int(earliest_t // 60)
                secs = int(earliest_t % 60)
                timestamp_str = f"{mins:02d}:{secs:02d}"
                camera_name = resolved_camera.name if resolved_camera else "Surveillance Camera"
                all_students = set(incident_student_observations.keys())
                for trk_id, primary_info in track_identity_cache.items():
                    if primary_info and primary_info.get("student"):
                        all_students.add(primary_info["student"].id)

                await AlertDispatcher.dispatch_violence_alert(
                    db=db,
                    video_id=target_video.id,
                    video_filename=target_video.original_filename or target_video.filename or "CCTV Video",
                    camera_name=camera_name,
                    incident_count=len(x3d_res.segments),
                    persons_identified_count=len(all_students),
                    earliest_timestamp_str=timestamp_str,
                    run_id=run_id
                )
            except Exception as ex:
                logger.warning(f"[VIOLENCE PIPELINE] Could not dispatch violence alert: {ex}")

        return await _compile_violence_dossier(db, target_video, resolved_camera)
    except Exception as exc:
        from app.tasks.video_tasks import is_video_cancelled
        if is_video_cancelled(target_video.id):
            logger.info(f"[VIOLENCE PIPELINE] Suppressed error for video {target_video.id} because it was deleted/cancelled.")
            return None

        logger.error(f'[VIOLENCE PIPELINE] Analysis failed for video {target_video.id}: {str(exc)}', exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass

        # Persist failed status reliably using an independent DB session
        from app.db.session import SessionLocal
        try:
            async with SessionLocal() as err_db:
                v_res = await err_db.execute(select(Video).filter(Video.id == target_video.id))
                err_video = v_res.scalars().first()
                if err_video:
                    err_video.status = 'failed'
                    err_video.current_stage = 'Analysis Failed'
                    err_video.error_message = f'Violence detection failed: {str(exc)}'[:1024]
                    err_video.processing_finished_at = datetime.now(timezone.utc)
                    await err_db.commit()
                    logger.info(f'[VIOLENCE PIPELINE] Successfully persisted failed status for video {target_video.id}')
        except Exception as db_err:
            logger.error(f'[VIOLENCE PIPELINE] Failed to persist failed video status: {db_err}')

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f'Violence detection analysis failed: {str(exc)}'
        )

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

        # DEFECT-DB-03 Remediation: Derive segment timing strictly from video-relative
        # X3D-M temporal segment bounds rather than wall-clock processing latency.
        seg_start_extracted = None
        seg_end_extracted = None
        seg_dur_extracted = None
        if inc.explanation:
            t_range_match = re.search(
                r"altercation from\s*([0-9]+(?:\.[0-9]+)?)s\s*to\s*([0-9]+(?:\.[0-9]+)?)s",
                inc.explanation
            )
            if t_range_match:
                seg_start_extracted = float(t_range_match.group(1))
                seg_end_extracted = float(t_range_match.group(2))
                seg_dur_extracted = max(0.1, round(seg_end_extracted - seg_start_extracted, 1))
            else:
                t_single_match = re.search(r"altercation (?:at|from)\s*([0-9]+(?:\.[0-9]+)?)s", inc.explanation)
                if t_single_match:
                    seg_start_extracted = float(t_single_match.group(1))

        det_event = next((e for e in inc.events if e.video_id == target_video.id), None)

        if seg_start_extracted is not None:
            timestamp_sec = seg_start_extracted
        else:
            # Fallback for legacy events without temporal range in explanation
            timestamp_sec = 0.0
            if det_event and det_event.timestamp and target_video.created_at:
                t_evt = det_event.timestamp.replace(tzinfo=None) if hasattr(det_event.timestamp, "tzinfo") and det_event.timestamp.tzinfo else det_event.timestamp
                t_vid = target_video.created_at.replace(tzinfo=None) if hasattr(target_video.created_at, "tzinfo") and target_video.created_at.tzinfo else target_video.created_at
                timestamp_sec = max(0.0, (t_evt - t_vid).total_seconds())

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
        seg_seen_student_ids = set()
        for ip in inc.persons:
            student = ip.student
            if not student and ip.student_id:
                s_res = await db.execute(select(Student).filter(Student.id == ip.student_id))
                student = s_res.scalars().first()

            if student and student.id not in seg_seen_student_ids:
                seg_seen_student_ids.add(student.id)
                photo_url = await _get_student_profile_photo_url(db, student.id)
                # Retrieve the track specifically identified as this student, or with this student's recognition
                tr_stmt = (
                    select(Track.id)
                    .filter(
                        Track.video_id == target_video.id,
                        Track.identified_student_id == student.id
                    )
                )
                rec_tr = (await db.execute(tr_stmt)).scalars().first()
                if not rec_tr:
                    rec_stmt = (
                        select(StudentRecognitionEvent.track_id)
                        .filter(
                            StudentRecognitionEvent.video_id == target_video.id,
                            StudentRecognitionEvent.student_id == student.id
                        )
                        .order_by(StudentRecognitionEvent.similarity_score.desc())
                    )
                    rec_tr = (await db.execute(rec_stmt)).scalars().first()

                card = InvolvedStudentCard(
                    student_id=student.id,
                    name=student.name,
                    roll_number=student.university_roll_number,
                    department=student.department,
                    programme=student.programme,
                    year=student.year,
                    semester=student.semester,
                    section=student.section,
                    class_name=f"{student.programme or ''} {student.section or ''}".strip() or "Student",
                    profile_photo_url=photo_url,
                    similarity_score=round(ip.confidence, 2),
                    confidence="high" if ip.confidence >= settings.RECOGNITION_HIGH_THRESHOLD else "medium",
                    track_id=str(rec_tr) if rec_tr else (str(det_event.track_id) if det_event and det_event.track_id else None),
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

        if seg_start_extracted is not None and seg_end_extracted is not None:
            start_t = seg_start_extracted
            end_t = seg_end_extracted
            duration = seg_dur_extracted or max(0.1, round(end_t - start_t, 1))
        elif seg_start_extracted is not None:
            start_t = seg_start_extracted
            duration = 6.0
            if target_video.duration and target_video.duration > 0:
                end_t = min(target_video.duration, start_t + duration)
                duration = max(0.1, round(end_t - start_t, 1))
            else:
                end_t = start_t + duration
        else:
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

        # Calculate true unique physical individuals (peak concurrent valid tracks) in this segment
        window_tracks = [
            trk for trk in all_video_tracks
            if not (trk.end_time < start_t or trk.start_time > end_t)
            and (trk.end_time - trk.start_time >= 0.15 or (trk.detections and len(trk.detections) >= 3))
        ]

        peak_concurrent_persons = 0
        if window_tracks:
            import numpy as np
            time_samples = np.arange(start_t, end_t + 0.1, 0.25)
            for ts in time_samples:
                c_active = sum(1 for trk in window_tracks if trk.start_time <= ts <= trk.end_time)
                if c_active > peak_concurrent_persons:
                    peak_concurrent_persons = c_active
            if peak_concurrent_persons == 0:
                peak_concurrent_persons = min(len(window_tracks), 2)
        elif all_video_tracks:
            # Fallback if window filtering is strict
            peak_concurrent_persons = 2

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

                disk_crop_path = trk.key_frame_path
                face_visible = bool(trk.identified_student_id or (disk_crop_path and "_face_" in disk_crop_path))

                matched_student = None
                id_confidence = "unidentified"
                sim_score = 0.0

                # 1. Check if track has identified_student_id in DB (authoritative assignment for this track)
                if trk.identified_student_id:
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
                        sim_score = 0.70
                        id_confidence = "high"

                # 2. Check if track already matched to a student in seg_students
                if not matched_student:
                    already_in_seg = next((s for s in seg_students if s.track_id == str(trk.id) and s.is_identified), None)
                    if already_in_seg and already_in_seg.student_id:
                        s_stmt = select(Student).filter(Student.id == already_in_seg.student_id)
                        s_res = await db.execute(s_stmt)
                        matched_student = s_res.scalars().first()
                        sim_score = already_in_seg.similarity_score
                        id_confidence = already_in_seg.confidence

                # 3. Check if track has an associated StudentRecognitionEvent in DB
                if not matched_student:
                    rec_check = await db.execute(
                        select(StudentRecognitionEvent)
                        .filter(StudentRecognitionEvent.track_id == trk.id)
                        .order_by(StudentRecognitionEvent.similarity_score.desc())
                    )
                    rec_obj = rec_check.scalars().first()
                    if rec_obj and rec_obj.student_id:
                        s_stmt = select(Student).filter(Student.id == rec_obj.student_id)
                        s_res = await db.execute(s_stmt)
                        matched_student = s_res.scalars().first()
                        if matched_student:
                            sim_score = rec_obj.similarity_score
                            id_confidence = rec_obj.confidence or ("high" if sim_score >= settings.RECOGNITION_HIGH_THRESHOLD else "medium")
                            face_visible = True

                # 4. Construct student card (only add confirmed matches to seg_students)
                if matched_student:
                    photo_url = await _get_student_profile_photo_url(db, matched_student.id)
                    student_card = InvolvedStudentCard(
                        student_id=matched_student.id,
                        name=matched_student.name,
                        roll_number=matched_student.university_roll_number,
                        department=matched_student.department,
                        programme=matched_student.programme,
                        year=matched_student.year,
                        semester=matched_student.semester,
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
                    student_card = InvolvedStudentCard(
                        student_id=None,
                        name="Unidentified Person",
                        roll_number="N/A",
                        department=None,
                        programme=None,
                        year=None,
                        semester=None,
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
            persons_count=peak_concurrent_persons,
            students=seg_students,
            tracks=seg_tracks
        ))

    # Also resolve any identified students from the entire video
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
                    year=student.year if student.year is not None else 1,
                    semester=student.semester if student.semester is not None else 1,
                    section=student.section,
                    class_name=f"{student.programme} {student.section}",
                    profile_photo_url=photo_url,
                    similarity_score=rec.similarity_score,
                    confidence=rec.confidence,
                    track_id=str(rec.track_id),
                    is_identified=True
                )

    # Ensure all segments in the altercation sequence contain the identified students
    if all_identified_students_map and segments:
        for seg in segments:
            for s_id, s_card in all_identified_students_map.items():
                if not any(st.student_id == s_id for st in seg.students if st.student_id):
                    seg.students.append(s_card)

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
    if not video or (video.uploaded_by != current_user.id and (current_user.role or "").lower() != "admin"):
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
    if not video or (video.uploaded_by != current_user.id and (current_user.role or "").lower() != "admin"):
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

    # Check for existing report for this incident
    stmt = select(Report).filter(Report.incident_id == inc.id)
    res = await db.execute(stmt)
    existing_rep = res.scalars().first()
    if existing_rep:
        logger.info(f"Report for violence incident {inc.id} already exists (id={existing_rep.id}). Returning existing report.")
        return {
            "success": True,
            "report_id": str(existing_rep.id),
            "title": existing_rep.title,
            "created_at": existing_rep.created_at.isoformat(),
            "incident_id": str(inc.id),
            "event_id": str(det_event.id) if det_event else str(inc.id),
            "data": existing_rep.data
        }

    report_obj = Report(
        id=uuid.uuid4(),
        title=report_title,
        incident_type="Violence",
        incident_id=inc.id,
        student_id=primary_student_id,
        created_at=datetime.now(timezone.utc),
        data=report_data
    )
    db.add(report_obj)
    try:
        await db.commit()
        await db.refresh(report_obj)
    except IntegrityError as exc:
        await db.rollback()
        # Concurrent race: fetch report created by winning concurrent transaction
        stmt = select(Report).filter(Report.incident_id == inc.id)
        res = await db.execute(stmt)
        existing_rep = res.scalars().first()
        if existing_rep:
            logger.info(
                f"Concurrent race resolved: Report for violence incident {inc.id} "
                f"already created (id={existing_rep.id}). Returning existing report."
            )
            return {
                "success": True,
                "report_id": str(existing_rep.id),
                "title": existing_rep.title,
                "created_at": existing_rep.created_at.isoformat(),
                "incident_id": str(inc.id),
                "event_id": str(det_event.id) if det_event else str(inc.id),
                "data": existing_rep.data
            }
        raise exc

    return {
        "success": True,
        "report_id": str(report_obj.id),
        "title": report_obj.title,
        "created_at": report_obj.created_at.isoformat(),
        "incident_id": str(inc.id),
        "event_id": str(det_event.id) if det_event else str(inc.id),
        "data": report_data
    }
