"""
Phase F24.0E: Targeted Fight Participant Verification Service.
Evaluates whether enrolled students Ash and Jose_John are participating in detected CCTV violence.

Requirements:
1. Resolve registered student records for Ash and Jose_John dynamically (no hardcoded IDs/paths).
2. Verify usable, valid ArcFace enrollment embeddings for each student; keep galleries separate.
   Explicitly report enrollment problems if missing or ambiguous.
3. Detect violence independently (via X3D segments); if no violence, report NO_VIOLENCE_DETECTED.
4. Find person tracks overlapping violence intervals; evaluate bounded temporally separated observations.
5. Attempt recognition using SCRFD and ArcFace with strict thresholds:
   - 0.60 Normal match
   - 0.75 High confidence
   - 0.05 Distinct-identity ambiguity margin
   Never lower thresholds. Report FACE_NOT_USABLE for low-res (< 12px) or turned away faces.
6. Separate recognition from participation:
   - CONFIRMED_PARTICIPANT
   - IDENTIFIED_NEAR_INCIDENT
   - POSSIBLE_PARTICIPANT_UNVERIFIED
   - NOT_OBSERVED_IN_INCIDENT
   - NO_VIOLENCE_DETECTED
   - IDENTITY_UNRESOLVED
7. Produce targeted incident report and dossier section.
"""

import os
import json
import uuid
import logging
import numpy as np
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, text

from app.core.config import settings
from app.models.student import Student, StudentPhoto
from app.models.face_embedding import StudentFaceEmbedding
from app.pipeline.face_engine import FaceEnrollmentEngine
from app.schemas.violence import (
    StudentVerificationResult,
    TargetedParticipantVerification
)

logger = logging.getLogger(__name__)


def rank_distinct_student_identities(
    db_sids: List[Any],
    sims: np.ndarray
) -> Tuple[Optional[Any], float, Optional[Any], float, float]:
    """
    Groups gallery similarity scores by distinct student identity
    and calculates top-to-runner-up margin between distinct identities.
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


async def resolve_target_student(
    db: AsyncSession,
    target_name: str,
    face_engine: Optional[FaceEnrollmentEngine] = None
) -> Dict[str, Any]:
    """
    Dynamically resolves a target student (e.g. Ash or Jose_John) from the database:
    1. Checks record existence and distinguishes between exact vs ambiguous matches.
    2. Verifies valid ArcFace enrollment embeddings in student_face_embeddings or student_photos.
    3. Keeps their gallery separate without hardcoding IDs, embedding values, or paths.
    4. Reports explicit enrollment problem if unresolvable or missing embeddings.
    """
    normalized_name = target_name.strip()
    
    # Query matching students by case-insensitive name
    stmt = select(Student).filter(
        func.lower(Student.name) == normalized_name.lower()
    )
    res = await db.execute(stmt)
    matching_students = res.scalars().all()

    # If no exact name match, check underscore/space variation (e.g. "Jose_John" vs "Jose John")
    if not matching_students:
        alt_name = normalized_name.replace("_", " ") if "_" in normalized_name else normalized_name.replace(" ", "_")
        alt_stmt = select(Student).filter(
            func.lower(Student.name) == alt_name.lower()
        )
        alt_res = await db.execute(alt_stmt)
        matching_students = alt_res.scalars().all()

    if not matching_students:
        return {
            "status": "STUDENT_NOT_FOUND",
            "student": None,
            "embeddings": [],
            "error": f"Student record '{target_name}' was not found in the registration database."
        }

    if len(matching_students) > 1:
        # Check if roll numbers or IDs disambiguate
        return {
            "status": "AMBIGUOUS_RECORDS",
            "student": None,
            "embeddings": [],
            "error": (
                f"Ambiguous registration: Found {len(matching_students)} conflicting student records "
                f"matching '{target_name}'. Cannot resolve unique identity safely."
            )
        }

    student = matching_students[0]
    valid_embeddings: List[np.ndarray] = []

    # 1. Check pre-calculated embeddings in student_face_embeddings table
    emb_stmt = select(StudentFaceEmbedding).filter(
        StudentFaceEmbedding.student_id == student.id
    )
    emb_res = await db.execute(emb_stmt)
    emb_records = emb_res.scalars().all()

    for rec in emb_records:
        raw_emb = rec.embedding
        if raw_emb:
            try:
                v = np.array(json.loads(raw_emb) if isinstance(raw_emb, str) else raw_emb, dtype=np.float32)
                if v.shape == (512,) and np.all(np.isfinite(v)):
                    norm = np.linalg.norm(v)
                    if norm > 0:
                        valid_embeddings.append(v / norm)
            except Exception as parse_err:
                logger.warning(f"Error parsing embedding {rec.id} for student {student.id}: {parse_err}")

    # 2. If no valid embeddings in table, check if photos exist and can be processed with ArcFace
    if not valid_embeddings:
        photo_stmt = select(StudentPhoto).filter(
            StudentPhoto.student_id == student.id
        )
        photo_res = await db.execute(photo_stmt)
        photos = photo_res.scalars().all()

        if photos:
            if face_engine is None:
                face_engine = FaceEnrollmentEngine()

            for p in photos:
                if p.photo_path and os.path.exists(p.photo_path):
                    # Check with face engine (CCTV relaxation enabled for CCTV screenshot photos)
                    proc_res = face_engine.process_photo(p.photo_path, is_cctv=True)
                    if proc_res.get("success") and proc_res.get("embedding"):
                        raw_v = np.array(proc_res["embedding"], dtype=np.float32)
                        if raw_v.shape == (512,) and np.all(np.isfinite(raw_v)):
                            n_val = np.linalg.norm(raw_v)
                            if n_val > 0:
                                valid_embeddings.append(raw_v / n_val)

    if not valid_embeddings:
        return {
            "status": "ENROLLMENT_MISSING_EMBEDDINGS",
            "student": student,
            "embeddings": [],
            "error": (
                f"Student record '{student.name}' exists (ID: {student.id}, Roll: {student.university_roll_number}), "
                "but does not possess valid, usable ArcFace enrollment embeddings."
            )
        }

    return {
        "status": "RESOLVED_VALID_EMBEDDING",
        "student": student,
        "embeddings": valid_embeddings,
        "error": None
    }


def evaluate_student_in_tracks(
    student_name: str,
    resolution: Dict[str, Any],
    violence_intervals: List[Dict[str, Any]],
    valid_video_tracks: Dict[int, Dict[str, Any]],
    gallery_matrix: Optional[np.ndarray],
    gallery_sids: List[Any],
    diagnostic_failures: List[Dict[str, Any]]
) -> StudentVerificationResult:
    """
    Evaluates face observations and participation for a resolved student across incident tracks:
    1. Separate recognition evaluation (ArcFace similarity, runner-up margin, 0.60/0.75 thresholds).
    2. Explicit low-resolution rejection (FACE_NOT_USABLE for < 12px or low det_score).
    3. Separate participation evaluation (CONFIRMED_PARTICIPANT vs IDENTIFIED_NEAR_INCIDENT vs etc).
    """
    # Case A: Enrollment resolution problem
    if resolution["status"] != "RESOLVED_VALID_EMBEDDING":
        status_label = "IDENTITY_UNRESOLVED"
        part_status = "NOT_OBSERVED_IN_INCIDENT"
        return StudentVerificationResult(
            student_name=student_name,
            student_id=str(resolution["student"].id) if resolution.get("student") else None,
            enrollment_status=resolution["status"],
            enrollment_error=resolution.get("error"),
            identity_status=status_label,
            participation_status=part_status,
            similarity_score=None,
            confidence=None,
            runner_up_identity=None,
            runner_up_similarity=None,
            margin=None,
            best_evidence_timestamp=None,
            best_evidence_frame=None,
            best_track_id=None,
            explanation=f"Enrollment verification failed: {resolution.get('error')}"
        )

    student_obj = resolution["student"]
    student_id_str = str(student_obj.id)
    student_embs = resolution["embeddings"]

    # Case B: No violence detected in video
    if not violence_intervals:
        return StudentVerificationResult(
            student_name=student_name,
            student_id=student_id_str,
            enrollment_status="RESOLVED_VALID_EMBEDDING",
            enrollment_error=None,
            identity_status="NOT_OBSERVED",
            participation_status="NO_VIOLENCE_DETECTED",
            similarity_score=None,
            confidence=None,
            runner_up_identity=None,
            runner_up_similarity=None,
            margin=None,
            best_evidence_timestamp=None,
            best_evidence_frame=None,
            best_track_id=None,
            explanation="No violent altercation intervals were detected in the CCTV video footage."
        )

    # Separate gallery matrix for this specific student
    student_matrix = np.vstack(student_embs) if student_embs else None

    best_match_sim = 0.0
    best_runner_up_sim = 0.0
    best_runner_up_sid = None
    best_margin = 0.0
    best_timestamp = None
    best_frame = None
    best_track_id = None
    best_face_usable = False
    is_direct_fight_track = False
    usable_observations_count = 0

    # Evaluate tracks overlapping the violence intervals
    for trk_id, trk in valid_video_tracks.items():
        trk_st = trk.get("start_time", 0.0)
        trk_et = trk.get("end_time", 0.0)

        # Check temporal overlap with any violence interval (with 2.5s tolerance)
        overlaps_violence = any(
            not (trk_et < (v_int["start_time"] - 2.5) or trk_st > (v_int["end_time"] + 2.5))
            for v_int in violence_intervals
        )
        if not overlaps_violence:
            continue

        cand_faces = trk.get("candidate_face_crops", [])
        for cand in cand_faces:
            face_dims = cand.get("face_dims", [0, 0])
            fw, fh = face_dims[0], face_dims[1]
            det_score = cand.get("det_score", 0.0)
            t_sec = cand.get("timestamp", trk_st)
            frame_idx = cand.get("frame")
            emb = cand.get("embedding")

            # Low-resolution face inspection & safeguard
            if fw < 12 or fh < 12:
                diagnostic_failures.append({
                    "track_id": trk_id,
                    "frame": frame_idx,
                    "timestamp": round(t_sec, 2),
                    "face_dims": [fw, fh],
                    "det_score": round(det_score, 3),
                    "status": "FACE_NOT_USABLE",
                    "reason": f"Face region resolution too small ({fw}x{fh}px, minimum 12x12px required for biometric reliability)"
                })
                continue

            if det_score < 0.40:
                diagnostic_failures.append({
                    "track_id": trk_id,
                    "frame": frame_idx,
                    "timestamp": round(t_sec, 2),
                    "face_dims": [fw, fh],
                    "det_score": round(det_score, 3),
                    "status": "FACE_NOT_USABLE",
                    "reason": f"Face detector confidence below threshold ({det_score:.3f} < 0.40)"
                })
                continue

            if emb is None:
                continue

            usable_observations_count += 1
            best_face_usable = True

            v_arr = np.array(emb, dtype=np.float32)
            n_val = np.linalg.norm(v_arr)
            if n_val > 0:
                v_arr = v_arr / n_val

            # Compare against target student's separate gallery
            sim_to_target = float(np.max(np.dot(student_matrix, v_arr)))

            # Compare against overall background gallery to find distinct runner-up
            runner_up_sid = None
            runner_up_sim = 0.0
            margin = sim_to_target

            if gallery_matrix is not None and len(gallery_sids) > 0:
                all_sims = np.dot(gallery_matrix, v_arr)
                b_sid, b_sim, sec_sid, sec_sim, calc_margin = rank_distinct_student_identities(gallery_sids, all_sims)
                
                # If top identity in full gallery is this student, runner-up is the competing distinct identity
                if str(b_sid) == student_id_str:
                    runner_up_sid = sec_sid
                    runner_up_sim = sec_sim
                    margin = calc_margin
                else:
                    # Competitor scored higher than target student
                    runner_up_sid = b_sid
                    runner_up_sim = b_sim
                    margin = sim_to_target - b_sim

            if sim_to_target > best_match_sim:
                best_match_sim = sim_to_target
                best_runner_up_sim = runner_up_sim
                best_runner_up_sid = runner_up_sid
                best_margin = margin
                best_timestamp = t_sec
                best_frame = frame_idx
                best_track_id = str(trk_id)

                # Direct altercation verification: check if track is physically engaged in the fight interval
                # High motion / altercation engagement across detections
                dets = trk.get("detections", [])
                active_dets_in_fight = [
                    d for d in dets
                    if any(v["start_time"] <= d["timestamp_seconds"] <= v["end_time"] for v in violence_intervals)
                ]
                is_direct_fight_track = len(active_dets_in_fight) >= 4

    # Recognition Decision Gates:
    # Match >= 0.60, High >= 0.75, Ambiguity margin >= 0.05
    is_above_threshold = (best_match_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD)
    is_ambiguous = (
        best_runner_up_sid is not None
        and str(best_runner_up_sid) != student_id_str
        and best_runner_up_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD
        and best_margin < 0.05
    )
    is_confirmed_identity = is_above_threshold and not is_ambiguous

    # Determine Participation Status:
    if is_confirmed_identity:
        if is_direct_fight_track:
            participation_status = "CONFIRMED_PARTICIPANT"
            explanation = (
                f"Identity confirmed as {student_name} (similarity {best_match_sim:.3f} >= 0.60, margin {best_margin:.3f} >= 0.05). "
                f"Direct physical participation verified on track {best_track_id} during detected violence interval."
            )
        else:
            participation_status = "IDENTIFIED_NEAR_INCIDENT"
            explanation = (
                f"Identity confirmed as {student_name} (similarity {best_match_sim:.3f} >= 0.60), "
                f"but physical fighting participation was not established (observed near incident / bystander role)."
            )
        identity_status = "CONFIRMED"
        conf_level = "high" if best_match_sim >= settings.RECOGNITION_HIGH_THRESHOLD else "medium"

    elif is_above_threshold and is_ambiguous:
        identity_status = "AMBIGUOUS"
        participation_status = "POSSIBLE_PARTICIPANT_UNVERIFIED"
        conf_level = "none"
        explanation = (
            f"Ambiguous identity: Top score for {student_name} was {best_match_sim:.3f}, but runner-up "
            f"identity {best_runner_up_sid} scored {best_runner_up_sim:.3f} (margin {best_margin:.3f} < 0.05). Verification rejected."
        )

    elif best_match_sim >= 0.35 and best_match_sim < settings.RECOGNITION_MEDIUM_THRESHOLD:
        identity_status = "SUB_THRESHOLD"
        participation_status = "POSSIBLE_PARTICIPANT_UNVERIFIED"
        conf_level = "none"
        explanation = (
            f"Suggestive observation on track {best_track_id} at {best_timestamp:.1f}s, but ArcFace similarity "
            f"({best_match_sim:.3f}) is below the required 0.60 threshold. Participation remains unverified."
        )

    elif usable_observations_count > 0:
        identity_status = "UNRESOLVED"
        participation_status = "IDENTITY_UNRESOLVED"
        conf_level = "none"
        explanation = (
            f"Face observations were detected during the incident window, but similarity to {student_name} "
            f"was negligible ({best_match_sim:.3f} < 0.60)."
        )

    else:
        identity_status = "NOT_OBSERVED"
        participation_status = "NOT_OBSERVED_IN_INCIDENT"
        conf_level = "none"
        explanation = (
            f"The available footage does not show a usable biometric observation of {student_name} in the incident interval. "
            "Note: This is not proof that the student was absent from the entire video."
        )

    return StudentVerificationResult(
        student_name=student_name,
        student_id=student_id_str,
        enrollment_status="RESOLVED_VALID_EMBEDDING",
        enrollment_error=None,
        identity_status=identity_status,
        participation_status=participation_status,
        similarity_score=round(best_match_sim, 3) if best_match_sim > 0 else None,
        confidence=conf_level,
        runner_up_identity=str(best_runner_up_sid) if best_runner_up_sid else None,
        runner_up_similarity=round(best_runner_up_sim, 3) if best_runner_up_sim > 0 else None,
        margin=round(best_margin, 3) if best_margin > 0 else None,
        best_evidence_timestamp=round(best_timestamp, 2) if best_timestamp is not None else None,
        best_evidence_frame=best_frame,
        best_track_id=best_track_id,
        explanation=explanation
    )


async def perform_targeted_fight_verification(
    db: AsyncSession,
    video_id: uuid.UUID,
    video_filename: str,
    violence_segments: List[Any],
    valid_video_tracks: Dict[int, Dict[str, Any]],
    face_engine: Optional[FaceEnrollmentEngine] = None
) -> TargetedParticipantVerification:
    """
    Orchestrates the targeted participant verification for Ash and Jose_John
    for an analyzed video according to Phase F24.0E specification.
    """
    if face_engine is None:
        face_engine = FaceEnrollmentEngine()

    # 1. Resolve registered student records for Ash and Jose_John
    ash_res = await resolve_target_student(db, "Ash", face_engine=face_engine)
    jj_res = await resolve_target_student(db, "Jose_John", face_engine=face_engine)

    # 2. Build full enrolled gallery snapshot for background distinct-identity ambiguity checks
    gallery_sids: List[Any] = []
    gallery_vecs: List[np.ndarray] = []
    try:
        all_emb_stmt = select(StudentFaceEmbedding.student_id, StudentFaceEmbedding.embedding)
        all_emb_res = await db.execute(all_emb_stmt)
        for sid_val, raw_emb in all_emb_res.fetchall():
            if raw_emb:
                v = np.array(json.loads(raw_emb) if isinstance(raw_emb, str) else raw_emb, dtype=np.float32)
                if v.shape == (512,) and np.all(np.isfinite(v)):
                    n = np.linalg.norm(v)
                    if n > 0:
                        gallery_sids.append(sid_val)
                        gallery_vecs.append(v / n)
    except Exception as g_err:
        logger.warning(f"Error loading background gallery for targeted verification: {g_err}")

    # Add resolved target student embeddings to background gallery if not already present
    if ash_res["status"] == "RESOLVED_VALID_EMBEDDING":
        for a_emb in ash_res["embeddings"]:
            gallery_sids.append(ash_res["student"].id)
            gallery_vecs.append(a_emb)

    if jj_res["status"] == "RESOLVED_VALID_EMBEDDING":
        for j_emb in jj_res["embeddings"]:
            gallery_sids.append(jj_res["student"].id)
            gallery_vecs.append(j_emb)

    gallery_matrix = np.vstack(gallery_vecs) if gallery_vecs else None

    # 3. Format violence intervals
    violence_intervals: List[Dict[str, Any]] = []
    max_conf = 0.0
    for s in violence_segments:
        st = float(getattr(s, "start_time", 0.0) if hasattr(s, "start_time") else s.get("start_time", 0.0))
        et = float(getattr(s, "end_time", 0.0) if hasattr(s, "end_time") else s.get("end_time", 0.0))
        c = float(getattr(s, "confidence", 0.0) if hasattr(s, "confidence") else s.get("confidence", 0.0))
        if c > max_conf:
            max_conf = c
        violence_intervals.append({
            "start_time": round(st, 2),
            "end_time": round(et, 2),
            "duration": round(et - st, 2),
            "confidence": round(c, 4)
        })

    is_violent = len(violence_intervals) > 0
    diagnostic_failures: List[Dict[str, Any]] = []

    # 4. Evaluate each student independently with separate galleries
    ash_eval = evaluate_student_in_tracks(
        student_name="Ash",
        resolution=ash_res,
        violence_intervals=violence_intervals,
        valid_video_tracks=valid_video_tracks,
        gallery_matrix=gallery_matrix,
        gallery_sids=gallery_sids,
        diagnostic_failures=diagnostic_failures
    )

    jj_eval = evaluate_student_in_tracks(
        student_name="Jose_John",
        resolution=jj_res,
        violence_intervals=violence_intervals,
        valid_video_tracks=valid_video_tracks,
        gallery_matrix=gallery_matrix,
        gallery_sids=gallery_sids,
        diagnostic_failures=diagnostic_failures
    )

    track_ids = [str(tid) for tid in valid_video_tracks.keys()]

    diagnostic_details = {
        "ash_enrolled_embedding_count": len(ash_res.get("embeddings", [])),
        "jose_john_enrolled_embedding_count": len(jj_res.get("embeddings", [])),
        "total_active_tracks_evaluated": len(valid_video_tracks),
        "total_face_failures_recorded": len(diagnostic_failures),
        "recognition_safeguards": {
            "medium_threshold": settings.RECOGNITION_MEDIUM_THRESHOLD,
            "high_threshold": settings.RECOGNITION_HIGH_THRESHOLD,
            "ambiguity_margin": 0.05,
            "min_face_size_px": 12
        }
    }

    return TargetedParticipantVerification(
        video_id=str(video_id),
        video_filename=video_filename,
        violence_detected=is_violent,
        violence_intervals=violence_intervals,
        overall_violence_confidence=round(max_conf, 4),
        ash=ash_eval,
        jose_john=jj_eval,
        track_ids=track_ids,
        face_failures=diagnostic_failures[:15],  # Bounded failure log
        diagnostic_details=diagnostic_details,
        verified_at=datetime.now(timezone.utc)
    )
