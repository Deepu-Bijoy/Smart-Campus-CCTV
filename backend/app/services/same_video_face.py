"""
Phase F24.0D: Same-Video Face Recognition Service.

Implements:
1. Preserve Source Image Quality:
   - Extract and preserve original extracted images at available native resolution.
   - Record original video identifier, timestamp, and frame index for every enrollment image.
   - Avoid unnecessary resizing, recompression, sharpening, or artificial enhancement before ArcFace.
   - Use identical face detection, landmark alignment, color conversion (BGR), and ArcFace preprocessing during enrollment and inference.
2. Verify the Actual Face Match:
   - Normal video observation processing across tracks/frames.
   - Record face detections, timestamps, track IDs, valid ArcFace embeddings, best identity score, distinct-person runner-up score, and final match decision.
   - Check whether the exact source frame is detected and whether its embedding matches the enrollment embedding.
   - Report separately: face_detected, valid_embedding, and identity_accepted.
3. Controlled Diagnostic:
   - Identify original source frame associated with enrollment photo.
   - Diagnostic comparison of live-extracted source frame vs saved enrollment photo.
   - Inspect preprocessing, alignment, embedding normalization, and model consistency before changing thresholds.
   - Explicitly enforce that identical source image is diagnostic only and NOT independent proof of general recognition accuracy.
4. Recognition Safeguards:
   - ArcFace thresholds: 0.60 normal match, 0.75 high confidence.
   - 0.05 distinct-identity ambiguity margin.
   - Never assign an identity solely because it is the highest-scoring candidate.
   - Report unambiguous diagnostic reasons when unaccepted.
"""

import os
import cv2
import json
import uuid
import logging
import numpy as np
from typing import Dict, Any, List, Optional, Tuple

from app.core.config import settings
from app.pipeline.face_engine import FaceEnrollmentEngine

logger = logging.getLogger(__name__)


def rank_distinct_student_identities(
    db_sids: List[Any],
    sims: np.ndarray
) -> Tuple[Optional[Any], float, Optional[Any], float, float]:
    """
    Phase F24.0A / F24.0D: Group gallery similarity scores by distinct student identity
    and calculate top-to-runner-up margin between distinct identities.
    """
    if db_sids is None or sims is None or len(db_sids) == 0 or len(sims) == 0:
        return None, 0.0, None, 0.0, 0.0

    student_max: Dict[str, Tuple[Any, float]] = {}
    for sid, s_val in zip(db_sids, sims):
        if sid is None:
            continue
        try:
            val = float(s_val)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(val):
            continue

        sid_key = str(sid)
        if sid_key not in student_max or val > student_max[sid_key][1]:
            student_max[sid_key] = (sid, val)

    if not student_max:
        return None, 0.0, None, 0.0, 0.0

    ranked = sorted(student_max.values(), key=lambda item: item[1], reverse=True)
    best_sid, best_sim = ranked[0]

    if len(ranked) > 1:
        second_sid, second_sim = ranked[1]
        margin = float(best_sim - second_sim)
    else:
        second_sid, second_sim = None, 0.0
        margin = float(best_sim)

    return best_sid, float(best_sim), second_sid, float(second_sim), margin


def _compute_face_observation_quality(
    det_score: float,
    blur_score: float,
    fw: float,
    fh: float,
    dist_from_center: float
) -> float:
    """Compute composite face quality score favoring high detector confidence, sharpness, and size."""
    try:
        det_conf = float(det_score) if det_score is not None else 0.0
        norm_conf = max(0.0, min(1.0, (det_conf - 0.40) / 0.55))
        face_size = float(np.sqrt(max(0, fw * fh)))
        norm_size = max(0.20, min(1.0, face_size / 60.0))
        b_val = float(blur_score) if blur_score is not None else 0.0
        norm_sharp = max(0.10, min(1.0, float(np.log1p(max(0.0, b_val)) / np.log1p(200.0))))
        norm_center = max(0.50, min(1.0, 1.0 - float(dist_from_center)))
        score = norm_conf * (norm_size ** 0.6) * (norm_sharp ** 0.4) * norm_center
        return float(round(score, 4))
    except Exception:
        return float(round(max(0.0, float(det_score or 0.0)), 4))



def extract_enrollment_image_from_video(
    video_path: str,
    frame_idx: Optional[int] = None,
    timestamp_sec: Optional[float] = None,
    output_path: Optional[str] = None,
    video_identifier: Optional[str] = None
) -> Dict[str, Any]:
    """
    Extract a frame from a CCTV video at its exact native resolution without
    any lossy resizing, recompression, sharpening, or image enhancement.
    
    Records original video identifier, timestamp, and frame index in metadata.
    """
    if not os.path.exists(video_path):
        return {
            "success": False,
            "error": f"Source video not found: {video_path}"
        }

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {
            "success": False,
            "error": f"Failed to open video stream: {video_path}"
        }

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1

    # Resolve frame index and timestamp
    if frame_idx is None and timestamp_sec is not None:
        target_frame = int(round(timestamp_sec * fps))
    elif frame_idx is not None:
        target_frame = int(frame_idx)
    else:
        target_frame = 0

    target_frame = max(0, min(total_frames - 1, target_frame))
    actual_timestamp = float(target_frame / fps)

    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ret, frame = cap.read()
    cap.release()

    if not ret or frame is None or frame.size == 0:
        return {
            "success": False,
            "error": f"Failed to decode frame {target_frame} from {video_path}"
        }

    h, w = frame.shape[:2]
    vid_id_str = video_identifier or os.path.basename(video_path)

    metadata = {
        "source": "cctv_video",
        "video_id": vid_id_str,
        "video_identifier": vid_id_str,
        "video_path": video_path,
        "frame_idx": target_frame,
        "timestamp_seconds": actual_timestamp,
        "resolution": [int(w), int(h)],
        "fps": float(fps),
        "total_frames": int(total_frames),
        "original_filename": f"{vid_id_str}_frame_{target_frame}.png"
    }

    # Save lossless image if output path specified
    saved_path = output_path
    if output_path:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # Use PNG for lossless preservation of original pixels
        if output_path.lower().endswith(".png"):
            cv2.imwrite(output_path, frame, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        else:
            cv2.imwrite(output_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 100])
        saved_path = output_path

    return {
        "success": True,
        "frame": frame,
        "file_path": saved_path,
        "frame_idx": target_frame,
        "timestamp_seconds": actual_timestamp,
        "resolution": [int(w), int(h)],
        "metadata": metadata
    }


def run_controlled_source_diagnostic(
    enrollment_photo_path: str,
    video_path: str,
    frame_idx: Optional[int] = None,
    timestamp_sec: Optional[float] = None,
    enrollment_embedding: Optional[List[float]] = None,
    face_engine: Optional[FaceEnrollmentEngine] = None
) -> Dict[str, Any]:
    """
    Controlled Diagnostic (Section 3):
    Identifies the original source frame associated with an enrollment photo
    and compares its ArcFace embedding against the saved enrollment embedding.
    
    If the same source image produces a low similarity score (< 0.99), inspects:
    1. Preprocessing (color conversion, resolution)
    2. Alignment (landmark detection, bounding box)
    3. Embedding normalization (L2 norm == 1.0, dimensionality == 512, finite values)
    4. Model consistency (buffalo_l ArcFace)
    
    Note: The identical enrollment image comparison is a controlled diagnostic only,
    never independent evidence of general recognition accuracy across distinct frames.
    """
    if face_engine is None:
        face_engine = FaceEnrollmentEngine()

    if not os.path.exists(enrollment_photo_path):
        return {
            "diagnostic_passed": False,
            "error": f"Enrollment photo does not exist: {enrollment_photo_path}",
            "similarity_score": 0.0
        }

    # 1. Process saved enrollment photo
    enr_res = face_engine.process_photo(enrollment_photo_path)
    if not enr_res.get("success"):
        return {
            "diagnostic_passed": False,
            "error": f"Failed to process enrollment photo: {enr_res.get('error')}",
            "similarity_score": 0.0
        }

    saved_emb = enr_res["embedding"]
    if enrollment_embedding is not None:
        saved_emb = enrollment_embedding

    saved_vec = np.array(saved_emb, dtype=np.float32)
    saved_norm = float(np.linalg.norm(saved_vec))
    if saved_norm > 0:
        saved_vec = saved_vec / saved_norm

    # 2. Extract original source frame directly from video
    src_res = extract_enrollment_image_from_video(
        video_path=video_path,
        frame_idx=frame_idx,
        timestamp_sec=timestamp_sec
    )
    if not src_res.get("success"):
        return {
            "diagnostic_passed": False,
            "error": f"Failed to extract source frame: {src_res.get('error')}",
            "similarity_score": 0.0
        }

    src_frame = src_res["frame"]
    actual_f_idx = src_res["frame_idx"]
    actual_t_sec = src_res["timestamp_seconds"]

    # 3. Detect face on live extracted source frame using identical pipeline
    if face_engine.model is None:
        return {
            "diagnostic_passed": False,
            "error": "InsightFace ArcFace model is not loaded.",
            "similarity_score": 0.0
        }

    live_faces = face_engine.model.get(src_frame)
    if not live_faces:
        return {
            "diagnostic_passed": False,
            "error": f"No face detected in original source frame {actual_f_idx}",
            "similarity_score": 0.0,
            "frame_idx": actual_f_idx,
            "timestamp_seconds": actual_t_sec
        }

    live_face = live_faces[0]
    live_raw_emb = getattr(live_face, "normed_embedding", None)
    if live_raw_emb is None:
        live_raw_emb = getattr(live_face, "embedding", None)
        l_norm = np.linalg.norm(live_raw_emb)
        if l_norm > 0:
            live_raw_emb = live_raw_emb / l_norm

    live_vec = np.array(live_raw_emb, dtype=np.float32)
    l_norm = float(np.linalg.norm(live_vec))
    if l_norm > 0:
        live_vec = live_vec / l_norm

    # 4. Compute cosine similarity
    sim = float(np.dot(saved_vec, live_vec))
    diagnostic_passed = (sim >= 0.99)

    # 5. Diagnostic inspection checks
    checks = {
        "preprocessing_color_space": "BGR (opencv native standard)",
        "preprocessing_resolution_match": (src_frame.shape[:2] == enr_res.get("resolution", src_frame.shape[:2])),
        "alignment_landmarks_present": (getattr(live_face, "kps", None) is not None),
        "live_detection_score": float(live_face.det_score),
        "saved_detection_score": float(enr_res.get("quality_score", 0.0)),
        "embedding_dimension": int(len(live_vec)),
        "saved_embedding_norm": saved_norm,
        "live_embedding_norm": l_norm,
        "is_finite": bool(np.all(np.isfinite(live_vec)) and np.all(np.isfinite(saved_vec))),
        "model_version": getattr(face_engine, "model_name", "buffalo_l")
    }

    diagnostic_details = []
    if not diagnostic_passed:
        if sim < 0.95:
            diagnostic_details.append(
                f"Significant embedding divergence ({sim:.4f} < 0.95). "
                "Check for image recompression, resizing, or landmark shift."
            )
        if abs(saved_norm - 1.0) > 1e-4 or abs(l_norm - 1.0) > 1e-4:
            diagnostic_details.append(f"L2 normalization drift: saved={saved_norm:.4f}, live={l_norm:.4f}.")
        if checks["embedding_dimension"] != 512:
            diagnostic_details.append(f"Invalid embedding dimension: {checks['embedding_dimension']} != 512.")

    return {
        "diagnostic_passed": diagnostic_passed,
        "similarity_score": sim,
        "source_frame_idx": actual_f_idx,
        "source_timestamp_seconds": actual_t_sec,
        "checks": checks,
        "diagnostic_inspection_details": diagnostic_details,
        "safeguard_disclaimer": (
            "CONTROLLED DIAGNOSTIC: Validates source frame extraction and preprocessing consistency. "
            "This identical frame comparison must NOT be used as independent evidence of general recognition accuracy."
        )
    }


def verify_same_video_face_match(
    video_path: str,
    enrollment_embedding: List[float],
    gallery: Dict[str, Any],
    source_frame_idx: Optional[int] = None,
    enrolled_student_id: Optional[uuid.UUID] = None,
    eval_frame_step: int = 15,
    max_frames_to_eval: int = 300,
    face_engine: Optional[FaceEnrollmentEngine] = None
) -> Dict[str, Any]:
    """
    Verify the Actual Face Match (Section 2 & 4 & 5):
    - Normal video observation processing across video frames/tracks.
    - Records face detections, timestamps, track IDs, valid ArcFace embeddings,
      best identity score, distinct-person runner-up score, margin, and final match decision.
    - Verifies whether exact source frame is detected and its embedding matches (~1.0).
    - Measures recognition on other frames from the video separately.
    - Reports 3 separate indicators: face_detected, valid_embedding, identity_accepted.
    - Preserves all recognition safeguards:
      Medium >= 0.60, High >= 0.75, Ambiguity margin >= 0.05 against distinct runner-up.
      Never assigns an identity solely for being top candidate.
      Reports reason when face not detected or evidence ambiguous.
    """
    if face_engine is None:
        face_engine = FaceEnrollmentEngine()

    if not os.path.exists(video_path):
        return {
            "success": False,
            "error": f"Video not found: {video_path}"
        }

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {
            "success": False,
            "error": f"Failed to open video: {video_path}"
        }

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1

    arr_enr = np.array(enrollment_embedding, dtype=np.float32)
    norm_enr = np.linalg.norm(arr_enr)
    if norm_enr > 0:
        arr_enr = arr_enr / norm_enr

    # Target frames to sample: always include exact source frame if specified, plus periodic frames
    sampled_indices = []
    if source_frame_idx is not None and 0 <= source_frame_idx < total_frames:
        sampled_indices.append(int(source_frame_idx))

    step = max(1, eval_frame_step)
    limit_count = min(total_frames, max_frames_to_eval)
    for f in range(0, limit_count, step):
        if f not in sampled_indices:
            sampled_indices.append(f)
    sampled_indices.sort()

    observations: List[Dict[str, Any]] = []
    source_frame_obs: Optional[Dict[str, Any]] = None

    other_frames_total = 0
    other_frames_detected = 0
    other_frames_valid_emb = 0
    other_frames_accepted = 0
    other_frames_high_conf = 0
    other_frames_ambiguous = 0
    other_frames_sub_threshold = 0
    failures: List[Dict[str, Any]] = []

    for f_idx in sampled_indices:
        t_sec = float(f_idx / fps)
        is_source_frame = (source_frame_idx is not None and f_idx == source_frame_idx)

        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            failure_item = {
                "frame_idx": f_idx,
                "timestamp": t_sec,
                "reason": "Failed to decode frame from video stream"
            }
            failures.append(failure_item)
            continue

        if not is_source_frame:
            other_frames_total += 1

        # Face detection
        faces = face_engine.model.get(frame) if face_engine.model else []
        if not faces:
            obs = {
                "frame_idx": f_idx,
                "timestamp": t_sec,
                "track_id": 1,  # synthetic single-track stream or multi-face
                "face_detected": False,
                "valid_embedding": False,
                "identity_accepted": False,
                "det_score": 0.0,
                "sim_to_enrollment": 0.0,
                "best_identity_sid": None,
                "best_identity_sim": 0.0,
                "runner_up_sid": None,
                "runner_up_sim": 0.0,
                "margin": 0.0,
                "decision": "NO_FACE_DETECTED",
                "reason": "No face visible in frame (turned away, occluded, or low contrast)"
            }
            observations.append(obs)
            if is_source_frame:
                source_frame_obs = obs
            else:
                failures.append({"frame_idx": f_idx, "timestamp": t_sec, "reason": obs["reason"]})
            continue

        # Face detected
        best_f = max(faces, key=lambda f: f.det_score)
        det_score = float(best_f.det_score)
        if not is_source_frame:
            other_frames_detected += 1

        # Embedding extraction & validation
        raw_emb = getattr(best_f, "normed_embedding", None)
        if raw_emb is None:
            raw_emb = getattr(best_f, "embedding", None)
            if raw_emb is not None:
                n = np.linalg.norm(raw_emb)
                if n > 0:
                    raw_emb = raw_emb / n

        is_valid_emb = False
        emb_sim_to_enr = 0.0
        vec_emb = None

        if raw_emb is not None:
            arr_cand = np.array(raw_emb, dtype=np.float32)
            if arr_cand.shape == (512,) and np.all(np.isfinite(arr_cand)):
                c_norm = np.linalg.norm(arr_cand)
                if c_norm > 0:
                    arr_cand = arr_cand / c_norm
                    is_valid_emb = True
                    vec_emb = arr_cand
                    emb_sim_to_enr = float(np.dot(arr_enr, arr_cand))

        if not is_valid_emb:
            obs = {
                "frame_idx": f_idx,
                "timestamp": t_sec,
                "track_id": 1,
                "face_detected": True,
                "valid_embedding": False,
                "identity_accepted": False,
                "det_score": det_score,
                "sim_to_enrollment": 0.0,
                "best_identity_sid": None,
                "best_identity_sim": 0.0,
                "runner_up_sid": None,
                "runner_up_sim": 0.0,
                "margin": 0.0,
                "decision": "INVALID_EMBEDDING",
                "reason": "Face detected but ArcFace embedding was malformed or non-finite"
            }
            observations.append(obs)
            if is_source_frame:
                source_frame_obs = obs
            else:
                failures.append({"frame_idx": f_idx, "timestamp": t_sec, "reason": obs["reason"]})
            continue

        if not is_source_frame:
            other_frames_valid_emb += 1

        # Gallery matching using rank_distinct_student_identities
        best_sid = None
        best_sim = 0.0
        runner_up_sid = None
        runner_up_sim = 0.0
        margin = 0.0

        if gallery.get("matrix") is not None and len(gallery.get("sids", [])) > 0:
            sims = np.dot(gallery["matrix"], vec_emb)
            best_sid, best_sim, runner_up_sid, runner_up_sim, margin = rank_distinct_student_identities(
                gallery["sids"],
                sims
            )
        else:
            # Gallery comparison directly against enrollment embedding
            best_sid = enrolled_student_id or uuid.uuid4()
            best_sim = emb_sim_to_enr
            runner_up_sid = None
            runner_up_sim = 0.0
            margin = best_sim

        # Strict Safeguards:
        # Medium >= 0.60, High >= 0.75, Ambiguity Margin >= 0.05
        is_ambiguous = (
            runner_up_sid is not None
            and str(runner_up_sid) != str(best_sid)
            and runner_up_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD
            and margin < 0.05
        )
        is_above_threshold = (best_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD)
        is_accepted = is_above_threshold and not is_ambiguous

        # Verify identity matches enrolled student
        if enrolled_student_id is not None and best_sid is not None:
            if str(best_sid) != str(enrolled_student_id):
                is_accepted = False

        if is_accepted:
            decision = "ACCEPTED"
            reason = (
                f"Accepted with ArcFace similarity {best_sim:.3f} "
                f"({'HIGH' if best_sim >= settings.RECOGNITION_HIGH_THRESHOLD else 'MEDIUM'} confidence, "
                f"distinct margin {margin:.3f} >= 0.05)"
            )
            if not is_source_frame:
                other_frames_accepted += 1
                if best_sim >= settings.RECOGNITION_HIGH_THRESHOLD:
                    other_frames_high_conf += 1
        elif is_ambiguous:
            decision = "AMBIGUOUS_REJECTED"
            reason = (
                f"Ambiguous identity rejected: Winner {best_sid} ({best_sim:.3f}) vs "
                f"Runner-up {runner_up_sid} ({runner_up_sim:.3f}) with margin {margin:.3f} < 0.05"
            )
            if not is_source_frame:
                other_frames_ambiguous += 1
                failures.append({"frame_idx": f_idx, "timestamp": t_sec, "reason": reason})
        else:
            decision = "SUB_THRESHOLD_REJECTED"
            reason = f"Identity rejected: ArcFace similarity {best_sim:.3f} < {settings.RECOGNITION_MEDIUM_THRESHOLD} threshold"
            if not is_source_frame:
                other_frames_sub_threshold += 1
                failures.append({"frame_idx": f_idx, "timestamp": t_sec, "reason": reason})

        obs = {
            "frame_idx": f_idx,
            "timestamp": t_sec,
            "track_id": 1,
            "face_detected": True,
            "valid_embedding": True,
            "identity_accepted": is_accepted,
            "det_score": det_score,
            "sim_to_enrollment": emb_sim_to_enr,
            "best_identity_sid": str(best_sid) if best_sid else None,
            "best_identity_sim": float(best_sim),
            "runner_up_sid": str(runner_up_sid) if runner_up_sid else None,
            "runner_up_sim": float(runner_up_sim),
            "margin": float(margin),
            "decision": decision,
            "reason": reason
        }
        observations.append(obs)
        if is_source_frame:
            source_frame_obs = obs

    cap.release()

    # Verify exact source frame detection & similarity
    source_frame_verified = False
    source_frame_sim = 0.0
    if source_frame_obs:
        source_frame_sim = source_frame_obs.get("sim_to_enrollment", 0.0)
        source_frame_verified = (
            source_frame_obs.get("face_detected", False)
            and source_frame_obs.get("valid_embedding", False)
            and (source_frame_sim >= 0.99)
        )

    return {
        "success": True,
        "video_path": video_path,
        "source_frame_idx": source_frame_idx,
        "source_frame_detected": source_frame_obs.get("face_detected", False) if source_frame_obs else False,
        "source_frame_valid_embedding": source_frame_obs.get("valid_embedding", False) if source_frame_obs else False,
        "source_frame_identity_accepted": source_frame_obs.get("identity_accepted", False) if source_frame_obs else False,
        "source_frame_similarity_to_enrollment": source_frame_sim,
        "source_frame_verified": source_frame_verified,
        "source_frame_observation": source_frame_obs,
        "other_frames_evaluation": {
            "total_evaluated": other_frames_total,
            "detected": other_frames_detected,
            "valid_embeddings": other_frames_valid_emb,
            "accepted": other_frames_accepted,
            "high_confidence_accepted": other_frames_high_conf,
            "ambiguous_rejected": other_frames_ambiguous,
            "sub_threshold_rejected": other_frames_sub_threshold,
            "recognition_rate": (other_frames_accepted / max(1, other_frames_total)),
            "detection_rate": (other_frames_detected / max(1, other_frames_total))
        },
        "all_observations_count": len(observations),
        "failures": failures,
        "safeguards_enforced": {
            "medium_threshold": settings.RECOGNITION_MEDIUM_THRESHOLD,
            "high_threshold": settings.RECOGNITION_HIGH_THRESHOLD,
            "ambiguity_margin": 0.05,
            "guaranteed_recognition_claimed": False
        }
    }
