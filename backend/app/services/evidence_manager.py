import os
import cv2
import json
import uuid
import logging
from typing import Optional, Dict, Any, List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.video import Video
from app.models.track import Track, Detection, PersonReid
from app.models.student import Student
from app.models.recognition import StudentRecognitionEvent
from app.core.config import settings

logger = logging.getLogger(__name__)

# In-memory cache of resolved evidence: (video_id, track_id, student_id) -> result dict
_evidence_cache: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
_INDEX_FILE = os.path.join(settings.STORAGE_DIR, "evidence", "evidence_index.json")


def _load_persisted_index() -> Dict[str, Any]:
    try:
        if os.path.exists(_INDEX_FILE):
            with open(_INDEX_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not load evidence index: {str(e)}")
    return {}


def _save_persisted_index(index: Dict[str, Any]) -> None:
    try:
        os.makedirs(os.path.dirname(_INDEX_FILE), exist_ok=True)
        with open(_INDEX_FILE, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)
    except Exception as e:
        logger.warning(f"Could not save evidence index: {str(e)}")


def format_seconds_to_hhmmss(seconds: Optional[float]) -> str:
    """Formats floating-point seconds into video-relative HH:MM:SS."""
    if seconds is None:
        return "00:00:00"
    total_sec = max(0, int(round(seconds)))
    h = total_sec // 3600
    m = (total_sec % 3600) // 60
    s = total_sec % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def normalize_storage_url(path: Optional[str]) -> Optional[str]:
    """Normalizes a filesystem or relative path into a web-accessible /storage/ URL."""
    if not path:
        return None
    url = path.replace("\\", "/")
    if "storage/" in url:
        return "/" + url[url.find("storage/"):]
    if not url.startswith("/"):
        return "/" + url
    return url


def draw_bounding_box_overlay(
    frame: Any,
    bounding_box: List[float],
    label: Optional[str] = None,
    color: Tuple[int, int, int] = (0, 215, 255)
) -> Any:
    """
    Renders a high-visibility, crisp bounding box and optional identification label tag
    on the full evidence frame.
    bounding_box expected in [x1, y1, x2, y2] format.
    """
    try:
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bounding_box
        ix1 = max(0, min(w - 1, int(round(x1))))
        iy1 = max(0, min(h - 1, int(round(y1))))
        ix2 = max(0, min(w, int(round(x2))))
        iy2 = max(0, min(h, int(round(y2))))

        if ix2 <= ix1 or iy2 <= iy1:
            return frame

        # Draw box outline
        cv2.rectangle(frame, (ix1, iy1), (ix2, iy2), color, 2)

        # Draw top label header
        if label:
            font = cv2.FONT_HERSHEY_SIMPLEX
            font_scale = 0.5
            thickness = 1
            (lw, lh), baseline = cv2.getTextSize(label, font, font_scale, thickness)
            
            tag_y1 = max(0, iy1 - lh - 8)
            tag_y2 = iy1
            tag_x2 = min(w, ix1 + lw + 10)
            
            cv2.rectangle(frame, (ix1, tag_y1), (tag_x2, tag_y2), color, -1)
            text_y = tag_y2 - 4
            cv2.putText(frame, label, (ix1 + 5, text_y), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)

        return frame
    except Exception as e:
        logger.warning(f"Failed to overlay bounding box: {str(e)}")
        return frame


def generate_full_frame_evidence(
    video_path: str,
    timestamp_seconds: float,
    output_path: str,
    bounding_box: Optional[List[float]] = None,
    label: Optional[str] = None
) -> bool:
    """
    Extracts the source video frame at timestamp_seconds, applies bounding-box annotations
    if provided, and saves the resulting full evidence screenshot to output_path.
    """
    if not os.path.exists(video_path):
        logger.warning(f"Source video not found: {video_path}")
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.warning(f"Could not open video file: {video_path}")
        return False

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            cap.release()
            return False

        target_frame = max(0, min(int(round(timestamp_seconds * fps)), total_frames - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()

        if not ret or frame is None or frame.size == 0:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()

        cap.release()

        if not ret or frame is None or frame.size == 0:
            return False

        # Apply bounding box annotation if requested
        if bounding_box and len(bounding_box) == 4:
            frame = draw_bounding_box_overlay(frame, bounding_box, label=label)

        success = cv2.imwrite(output_path, frame)
        return bool(success and os.path.exists(output_path) and os.path.getsize(output_path) > 0)
    except Exception as e:
        logger.error(f"Error generating full-frame evidence: {str(e)}")
        if cap.isOpened():
            cap.release()
        return False


def get_or_create_general_evidence_frame(
    video: Video,
    timestamp_seconds: float,
    bounding_box: Optional[List[float]] = None,
    label: Optional[str] = None,
    tracker_id: Optional[int] = None
) -> Tuple[Optional[str], bool]:
    """
    Extracts and returns a full evidence frame for general appearances or incidents.
    Returns (url, is_nearby).
    """
    evidence_dir = os.path.join(settings.STORAGE_DIR, "evidence")
    os.makedirs(evidence_dir, exist_ok=True)

    trk_str = f"trk{tracker_id}" if tracker_id is not None else "gen"
    ts_ms = int(round(timestamp_seconds * 1000))
    out_filename = f"evidence_frame_{video.id}_{trk_str}_{ts_ms}.jpg"
    out_filepath = os.path.join(evidence_dir, out_filename)

    if os.path.exists(out_filepath) and os.path.getsize(out_filepath) > 0:
        return normalize_storage_url(out_filepath), False

    if video.file_path and os.path.exists(video.file_path):
        ok = generate_full_frame_evidence(
            video_path=video.file_path,
            timestamp_seconds=timestamp_seconds,
            output_path=out_filepath,
            bounding_box=bounding_box,
            label=label
        )
        if ok:
            return normalize_storage_url(out_filepath), False

    # Check for nearby frames
    candidate_frames = [
        f for f in os.listdir(evidence_dir)
        if str(video.id)[:8] in f and f.endswith(".jpg")
    ]
    if candidate_frames:
        fallback_path = os.path.join(evidence_dir, candidate_frames[0])
        return normalize_storage_url(fallback_path), True

    return None, False


async def resolve_student_track_evidence(
    db: AsyncSession,
    video: Video,
    track: Optional[Track],
    student: Student,
    group_events: List[StudentRecognitionEvent]
) -> Dict[str, Any]:
    """
    Identifies the precise detection record and video-relative timestamp where the student
    identity was verified on this track, generates or retrieves the full evidence frame
    with a bounding box, offers the companion person crop separately, and ensures
    student identification details strictly correspond to the evidence screenshot.
    """
    track_id_str = str(track.id) if track else "no_track"
    cache_key = (str(video.id), track_id_str, str(student.id))
    
    # 1. In-memory cache check
    if cache_key in _evidence_cache:
        cached = _evidence_cache[cache_key]
        local_img = cached.get("_local_evidence_path")
        if not local_img or os.path.exists(local_img):
            return cached

    # 2. Persisted index check
    persisted_idx = _load_persisted_index()
    idx_key = f"{video.id}_{track_id_str}_{student.id}"
    if idx_key in persisted_idx:
        p_data = persisted_idx[idx_key]
        local_img = p_data.get("_local_evidence_path")
        if not local_img or os.path.exists(local_img):
            _evidence_cache[cache_key] = p_data
            return p_data

    # 3. Fetch detections for this track ordered chronologically
    dets: List[Detection] = []
    reids: List[PersonReid] = []
    if track:
        det_stmt = (
            select(Detection)
            .filter(Detection.track_id == track.id)
            .order_by(Detection.timestamp_seconds.asc())
        )
        det_res = await db.execute(det_stmt)
        dets = det_res.scalars().all()

        reid_stmt = (
            select(PersonReid)
            .filter(PersonReid.track_id == track.id)
            .order_by(PersonReid.timestamp_seconds.asc())
        )
        reid_res = await db.execute(reid_stmt)
        reids = reid_res.scalars().all()

    # 4. Locate the specific detection where the face match occurred
    target_ts: Optional[float] = None
    target_bbox: Optional[List[float]] = None
    target_crop_path: Optional[str] = None
    is_nearby = False

    # Strategy A: If reids exist, locate the crop where face was recognized
    matched_reid = None
    if reids:
        from app.services.student_identifier import StudentIdentifier
        identifier = StudentIdentifier()
        for r in reids:
            if not r.crop_path or not os.path.exists(r.crop_path):
                continue
            try:
                res = await identifier.identify_face_in_crop(r.crop_path)
                if res and res.get("success") and res.get("student_id") == student.id:
                    matched_reid = r
                    break
            except Exception:
                continue

    if matched_reid:
        target_ts = float(matched_reid.timestamp_seconds)
        target_crop_path = matched_reid.crop_path
        if dets:
            closest_det = min(dets, key=lambda d: abs(float(d.timestamp_seconds) - target_ts))
            target_bbox = closest_det.bounding_box
    elif track and track.key_frame_path and os.path.exists(track.key_frame_path):
        # Strategy B: Track keyframe (e.g. from violence detection or ByteTrack keyframe)
        target_crop_path = track.key_frame_path
        target_ts = float(track.start_time) if track.start_time is not None else 0.0
        if dets:
            closest_det = min(dets, key=lambda d: abs(float(d.timestamp_seconds) - target_ts))
            target_bbox = closest_det.bounding_box
            target_ts = float(closest_det.timestamp_seconds)
    elif dets:
        # Strategy C: Earliest detection on track
        target_ts = float(dets[0].timestamp_seconds)
        target_bbox = dets[0].bounding_box
        is_nearby = True
    elif track and track.start_time is not None:
        target_ts = float(track.start_time)
        is_nearby = True
    else:
        target_ts = 0.0
        is_nearby = True

    # 5. Generate or locate full evidence frame
    evidence_dir = os.path.join(settings.STORAGE_DIR, "evidence")
    os.makedirs(evidence_dir, exist_ok=True)

    tracker_id_str = f"trk{track.tracker_id}" if track and track.tracker_id is not None else "trk"
    frame_ts_ms = int(round(target_ts * 1000))
    evidence_filename = f"evidence_frame_{video.id}_{tracker_id_str}_{frame_ts_ms}.jpg"
    evidence_filepath = os.path.join(evidence_dir, evidence_filename)

    label_str = f"{student.name} (Roll: {student.university_roll_number or 'N/A'})"
    evidence_url: Optional[str] = None

    if os.path.exists(evidence_filepath) and os.path.getsize(evidence_filepath) > 0:
        evidence_url = normalize_storage_url(evidence_filepath)
    elif video.file_path and os.path.exists(video.file_path):
        success = generate_full_frame_evidence(
            video_path=video.file_path,
            timestamp_seconds=target_ts,
            output_path=evidence_filepath,
            bounding_box=target_bbox,
            label=label_str
        )
        if success:
            evidence_url = normalize_storage_url(evidence_filepath)

    # Fallback to existing nearby evidence frame if extraction failed
    if not evidence_url:
        candidate_frames = [
            f for f in os.listdir(evidence_dir)
            if str(video.id)[:8] in f and f.endswith(".jpg")
        ]
        if candidate_frames:
            fallback_path = os.path.join(evidence_dir, candidate_frames[0])
            evidence_url = normalize_storage_url(fallback_path)
            is_nearby = True

    # Companion person crop URL
    person_crop_url = normalize_storage_url(target_crop_path) if target_crop_path and os.path.exists(target_crop_path) else None

    # Video clip URL
    video_url = normalize_storage_url(video.file_path) if video.file_path else None

    result = {
        "timestamp_seconds": float(target_ts),
        "timestamp": format_seconds_to_hhmmss(target_ts),
        "first_detection_timestamp": format_seconds_to_hhmmss(target_ts),
        "evidence_screenshot": evidence_url,
        "person_crop": person_crop_url,
        "is_nearby": is_nearby,
        "bounding_box": target_bbox,
        "video_url": video_url,
        "_local_evidence_path": evidence_filepath if evidence_url else None
    }

    _evidence_cache[cache_key] = result
    persisted_idx[idx_key] = result
    _save_persisted_index(persisted_idx)

    return result
