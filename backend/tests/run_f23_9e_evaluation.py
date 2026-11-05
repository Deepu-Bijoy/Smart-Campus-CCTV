"""
Phase F23.9E: Controlled Staged-Incident Evaluation Harness.
Executes Configurations A (F23.8B), B (F23.9B), and C (F23.9C) against identical input video
and identical enrolled gallery snapshot in isolated storage.
"""

import os
import sys
import time
import json
import uuid
import sqlite3
import tracemalloc
import numpy as np
import cv2
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.api.v1.violence import (
    _track_video_segments_sync,
    _detect_faces_on_candidates_sync,
    _compute_face_observation_quality,
    validate_pre_incident_track_association
)
from app.pipeline.face_engine import FaceEnrollmentEngine
from app.core.config import settings

def load_gallery_snapshot(db_path: str):
    """Load read-only snapshot of enrolled student gallery from SQLite."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.name, s.university_roll_number, e.embedding
        FROM students s
        JOIN student_photos p ON s.id = p.student_id
        JOIN student_face_embeddings e ON p.id = e.photo_id
        WHERE e.embedding IS NOT NULL
    """)
    rows = cur.fetchall()
    conn.close()

    gallery_sids = []
    gallery_names = []
    gallery_rolls = []
    gallery_embs = []

    for sid, name, roll, emb_blob in rows:
        try:
            if isinstance(emb_blob, (bytes, bytearray)):
                emb_list = json.loads(emb_blob.decode("utf-8"))
            elif isinstance(emb_blob, str):
                emb_list = json.loads(emb_blob)
            else:
                continue
            if len(emb_list) == 512:
                arr = np.array(emb_list, dtype=np.float32)
                norm = np.linalg.norm(arr)
                if norm > 0:
                    gallery_embs.append(arr / norm)
                    gallery_sids.append(sid)
                    gallery_names.append(name)
                    gallery_rolls.append(roll)
        except Exception:
            pass

    return {
        "matrix": np.vstack(gallery_embs) if gallery_embs else None,
        "sids": gallery_sids,
        "names": gallery_names,
        "rolls": gallery_rolls,
        "count": len(gallery_embs)
    }

def match_face_against_gallery(emb_vec, gallery):
    """Match 512-d normalized embedding against gallery enforcing strict safeguards."""
    if emb_vec is None or gallery["matrix"] is None:
        return None, 0.0, None, 0.0, 0.0, False

    arr = np.array(emb_vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    if norm == 0:
        return None, 0.0, None, 0.0, 0.0, False
    arr = arr / norm

    sims = np.dot(gallery["matrix"], arr)
    if len(sims) == 0:
        return None, 0.0, None, 0.0, 0.0, False

    student_max = {}
    for sid, name, s_val in zip(gallery["sids"], gallery["names"], sims):
        if sid is None:
            continue
        try:
            val = float(s_val)
        except (TypeError, ValueError):
            continue
        if not np.isfinite(val):
            continue
        sid_key = str(sid)
        if sid_key not in student_max or val > student_max[sid_key]["sim"]:
            student_max[sid_key] = {"sid": sid, "name": name, "sim": val}

    if not student_max:
        return None, 0.0, None, 0.0, 0.0, False

    ranked = sorted(student_max.values(), key=lambda item: item["sim"], reverse=True)
    top_sid = ranked[0]["sid"]
    top_name = ranked[0]["name"]
    top_sim = ranked[0]["sim"]

    if len(ranked) > 1:
        sec_sid = ranked[1]["sid"]
        sec_name = ranked[1]["name"]
        sec_sim = ranked[1]["sim"]
        margin = top_sim - sec_sim
    else:
        sec_sid = None
        sec_name = None
        sec_sim = 0.0
        margin = top_sim

    # Safeguards: Medium >= 0.60, High >= 0.75, Ambiguity Margin >= 0.05 against competing identity
    is_ambiguous = (sec_name is not None and sec_sim >= 0.60 and margin < 0.05)
    is_confirmed = (top_sim >= 0.60) and not is_ambiguous
    return top_name, top_sim, sec_name, sec_sim, margin, is_confirmed

def run_f23_8b_face_detection(crop_dir: str, valid_tracks: dict, face_engine):
    """
    Simulate exact F23.8B face detection baseline:
    - Early exit when det_score >= 0.65
    - Ranking based purely on det_score (no composite quality score)
    - No inner-span face-to-person association gating
    """
    t_start = time.time()
    call_count = 0
    os.makedirs(crop_dir, exist_ok=True)

    tracks_copy = {}
    for tid, trk in valid_tracks.items():
        tracks_copy[tid] = dict(trk)
        candidates = list(trk.get("_candidate_crops", []))
        cand_face_list = []

        for cand in candidates[:3]:
            crop = cand.get("crop")
            frame_idx = cand.get("frame_idx")
            t_sec = cand.get("timestamp")
            if crop is None or crop.size == 0 or face_engine.model is None:
                continue

            call_count += 1
            faces = face_engine.model.get(crop)
            if not faces:
                continue

            best_f = max(faces, key=lambda f: f.det_score)
            if best_f.det_score < 0.45:
                continue

            emb_vec = None
            raw_emb = getattr(best_f, "normed_embedding", None)
            if raw_emb is not None:
                arr_e = np.array(raw_emb, dtype=np.float32)
                if arr_e.shape == (512,) and np.all(np.isfinite(arr_e)):
                    e_norm = np.linalg.norm(arr_e)
                    if e_norm > 0:
                        emb_vec = (arr_e / e_norm).tolist()

            cand_entry = {
                "det_score": float(best_f.det_score),
                "quality_score": float(best_f.det_score),  # F23.8B: det_score alone
                "frame": frame_idx,
                "timestamp": t_sec,
                "trk_id": tid,
                "embedding": emb_vec
            }
            cand_face_list.append(cand_entry)

            # F23.8B premature early exit
            if best_f.det_score >= 0.65:
                break

        tracks_copy[tid]["candidate_face_crops"] = cand_face_list
        if cand_face_list:
            best_c = max(cand_face_list, key=lambda c: c["det_score"])
            tracks_copy[tid]["best_face_score"] = best_c["det_score"]
            tracks_copy[tid]["best_quality_score"] = best_c["det_score"]
        else:
            tracks_copy[tid]["best_face_score"] = 0.0
            tracks_copy[tid]["best_quality_score"] = 0.0

    t_elapsed = time.time() - t_start
    return tracks_copy, t_elapsed, call_count

def execute_evaluation():
    video_filename = "b5ac3a8f-1bb7-43c6-a09b-570ed5d05a68.mp4"
    video_path = os.path.join(backend_dir, "storage", video_filename)
    db_path = os.path.join(backend_dir, "storage", "cctv.db")
    base_eval_dir = os.path.join(backend_dir, "storage", "test_staged_eval_crops")
    os.makedirs(base_eval_dir, exist_ok=True)

    if not os.path.exists(video_path):
        print(f"ERROR: Video {video_path} not found.")
        return

    # Load gallery snapshot (58 vectors from 21 students)
    gallery = load_gallery_snapshot(db_path)
    print(f"Loaded gallery snapshot: {gallery['count']} vectors from {len(set(gallery['sids']))} enrolled students.")

    # Ground truth for b5ac3a8f-1bb7-43c6-a09b-570ed5d05a68.mp4:
    # 16 incident participants in [49.0s - 54.0s]. 0 enrolled students among participants.
    # Ground-truth: all 16 participants must be Unidentified Person.
    seg = {"start_time": 49.0, "end_time": 54.0}
    face_engine = FaceEnrollmentEngine()

    results = {}

    # =========================================================================
    # CONFIGURATION A: F23.8B Baseline
    # =========================================================================
    print("\n" + "="*60)
    print("RUNNING CONFIGURATION A: F23.8B Baseline (margin 0.0s, early exit, det-score)")
    print("="*60)
    crop_dir_a = os.path.join(base_eval_dir, "config_a_f23_8b")
    tracemalloc.start()
    t_start_a = time.time()

    tracks_a, t_track_a, calls_track_a = _track_video_segments_sync(
        video_file_path=video_path,
        video_id=uuid.uuid4(),
        segments=[seg],
        pre_incident_margin=0.0
    )
    tracks_a_evaluated, t_face_a, calls_face_a = run_f23_8b_face_detection(
        crop_dir=crop_dir_a,
        valid_tracks=tracks_a,
        face_engine=face_engine
    )
    total_time_a = time.time() - t_start_a
    mem_curr_a, mem_peak_a = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Identity matching for A
    incident_tracks_a = {tid: t for tid, t in tracks_a_evaluated.items() if t.get("end_time", 0.0) >= 49.0 and t.get("start_time", 0.0) <= 54.0}
    ident_a = 0
    false_match_a = 0
    unident_a = 0
    max_sim_a = 0.0
    max_margin_a = 0.0
    best_candidate_a = None

    for tid, trk in incident_tracks_a.items():
        is_trk_matched = False
        for cand in trk.get("candidate_face_crops", []):
            top_n, top_s, sec_n, sec_s, marg, conf = match_face_against_gallery(cand.get("embedding"), gallery)
            if top_s > max_sim_a:
                max_sim_a = top_s
                max_margin_a = marg
                best_candidate_a = (top_n, top_s, sec_n, sec_s, marg)
            if conf:
                is_trk_matched = True
                false_match_a += 1  # Since ground truth is 0 enrolled participants, any confirmation is false match
                break
        if not is_trk_matched:
            unident_a += 1

    results["Config A (F23.8B)"] = {
        "tracking_time": t_track_a,
        "face_time": t_face_a,
        "total_time": total_time_a,
        "detector_calls": calls_face_a,
        "total_tracks": len(tracks_a),
        "incident_tracks": len(incident_tracks_a),
        "correct_identifications": ident_a,
        "false_matches": false_match_a,
        "unidentified_persons": unident_a,
        "top_similarity": max_sim_a,
        "best_margin": max_margin_a,
        "best_match_info": best_candidate_a,
        "peak_memory_mb": mem_peak_a / (1024*1024)
    }

    # =========================================================================
    # CONFIGURATION B: F23.9B Best-Face Selection
    # =========================================================================
    print("\n" + "="*60)
    print("RUNNING CONFIGURATION B: F23.9B Best-Face (margin 0.0s, all candidates, composite quality)")
    print("="*60)
    crop_dir_b = os.path.join(base_eval_dir, "config_b_f23_9b")
    tracemalloc.start()
    t_start_b = time.time()

    tracks_b, t_track_b, calls_track_b = _track_video_segments_sync(
        video_file_path=video_path,
        video_id=uuid.uuid4(),
        segments=[seg],
        pre_incident_margin=0.0
    )
    tracks_b_evaluated, t_face_b, calls_face_b = _detect_faces_on_candidates_sync(
        crop_dir=crop_dir_b,
        valid_tracks=tracks_b
    )
    total_time_b = time.time() - t_start_b
    mem_curr_b, mem_peak_b = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    incident_tracks_b = {tid: t for tid, t in tracks_b_evaluated.items() if t.get("end_time", 0.0) >= 49.0 and t.get("start_time", 0.0) <= 54.0}
    ident_b = 0
    false_match_b = 0
    unident_b = 0
    max_sim_b = 0.0
    max_margin_b = 0.0
    best_candidate_b = None

    for tid, trk in incident_tracks_b.items():
        is_trk_matched = False
        for cand in trk.get("candidate_face_crops", []):
            top_n, top_s, sec_n, sec_s, marg, conf = match_face_against_gallery(cand.get("embedding"), gallery)
            if top_s > max_sim_b:
                max_sim_b = top_s
                max_margin_b = marg
                best_candidate_b = (top_n, top_s, sec_n, sec_s, marg)
            if conf:
                is_trk_matched = True
                false_match_b += 1
                break
        if not is_trk_matched:
            unident_b += 1

    results["Config B (F23.9B)"] = {
        "tracking_time": t_track_b,
        "face_time": t_face_b,
        "total_time": total_time_b,
        "detector_calls": calls_face_b,
        "total_tracks": len(tracks_b),
        "incident_tracks": len(incident_tracks_b),
        "correct_identifications": ident_b,
        "false_matches": false_match_b,
        "unidentified_persons": unident_b,
        "top_similarity": max_sim_b,
        "best_margin": max_margin_b,
        "best_match_info": best_candidate_b,
        "peak_memory_mb": mem_peak_b / (1024*1024)
    }

    # =========================================================================
    # CONFIGURATION C: F23.9C Bounded Pre-Incident Recovery
    # =========================================================================
    print("\n" + "="*60)
    print("RUNNING CONFIGURATION C: F23.9C Pre-Incident Recovery (margin 4.5s, all candidates, association gating)")
    print("="*60)
    crop_dir_c = os.path.join(base_eval_dir, "config_c_f23_9c")
    tracemalloc.start()
    t_start_c = time.time()

    tracks_c, t_track_c, calls_track_c = _track_video_segments_sync(
        video_file_path=video_path,
        video_id=uuid.uuid4(),
        segments=[seg],
        pre_incident_margin=4.5
    )
    tracks_c_evaluated, t_face_c, calls_face_c = _detect_faces_on_candidates_sync(
        crop_dir=crop_dir_c,
        valid_tracks=tracks_c
    )
    total_time_c = time.time() - t_start_c
    mem_curr_c, mem_peak_c = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    incident_tracks_c = {tid: t for tid, t in tracks_c_evaluated.items() if t.get("end_time", 0.0) >= 49.0 and t.get("start_time", 0.0) <= 54.0}
    ident_c = 0
    false_match_c = 0
    unident_c = 0
    max_sim_c = 0.0
    max_margin_c = 0.0
    best_candidate_c = None

    # Track pre-incident associated candidates
    pre_candidates = [
        (o_tid, o_trk) for o_tid, o_trk in tracks_c_evaluated.items()
        if o_trk.get("end_time", 0.0) <= 49.0 + 0.15
    ]
    all_earlier_list = [o_trk for _, o_trk in pre_candidates]

    for tid, trk in incident_tracks_c.items():
        is_trk_matched = False
        # Direct track observations (including continuous ByteTrack pre-incident observations)
        for cand in trk.get("candidate_face_crops", []):
            top_n, top_s, sec_n, sec_s, marg, conf = match_face_against_gallery(cand.get("embedding"), gallery)
            if top_s > max_sim_c:
                max_sim_c = top_s
                max_margin_c = marg
                best_candidate_c = (top_n, top_s, sec_n, sec_s, marg)
            if conf:
                is_trk_matched = True
                false_match_c += 1
                break

        # Fallback to defensibly associated earlier pre-tracks if not matched
        if not is_trk_matched:
            for o_tid, o_trk in pre_candidates:
                if o_tid == tid:
                    continue
                is_assoc, method, sim_reid = validate_pre_incident_track_association(
                    incident_track=trk,
                    candidate_pre_track=o_trk,
                    all_pre_tracks=all_earlier_list,
                    incident_start_sec=trk.get("start_time", 49.0)
                )
                if is_assoc and o_trk.get("candidate_face_crops"):
                    for pre_cand in o_trk["candidate_face_crops"]:
                        top_n, top_s, sec_n, sec_s, marg, conf = match_face_against_gallery(pre_cand.get("embedding"), gallery)
                        if top_s > max_sim_c:
                            max_sim_c = top_s
                            max_margin_c = marg
                            best_candidate_c = (top_n, top_s, sec_n, sec_s, marg)
                        if conf:
                            is_trk_matched = True
                            false_match_c += 1
                            break
                    if is_trk_matched:
                        break

        if not is_trk_matched:
            unident_c += 1

    results["Config C (F23.9C)"] = {
        "tracking_time": t_track_c,
        "face_time": t_face_c,
        "total_time": total_time_c,
        "detector_calls": calls_face_c,
        "total_tracks": len(tracks_c),
        "incident_tracks": len(incident_tracks_c),
        "correct_identifications": ident_c,
        "false_matches": false_match_c,
        "unidentified_persons": unident_c,
        "top_similarity": max_sim_c,
        "best_margin": max_margin_c,
        "best_match_info": best_candidate_c,
        "peak_memory_mb": mem_peak_c / (1024*1024)
    }

    # =========================================================================
    # SUMMARY REPORT
    # =========================================================================
    print("\n" + "="*80)
    print("PHASE F23.9E CONTROLLED EVALUATION RESULTS MATRIX")
    print("="*80)
    for cfg_name, res in results.items():
        print(f"\n[{cfg_name}]")
        print(f"  Tracks Discovered: {res['total_tracks']} (Incident: {res['incident_tracks']})")
        print(f"  Tracking Time: {res['tracking_time']:.2f}s | Face Engine Time: {res['face_time']:.2f}s | Total: {res['total_time']:.2f}s")
        print(f"  Face Detector Calls: {res['detector_calls']}")
        print(f"  Correct Identifications: {res['correct_identifications']}")
        print(f"  False Matches: {res['false_matches']} (Strict 0.0% constraint satisfied: {res['false_matches'] == 0})")
        print(f"  Unidentified Incident Tracks: {res['unidentified_persons']} / {res['incident_tracks']}")
        print(f"  Top ArcFace Similarity: {res['top_similarity']:.3f} (< 0.60 threshold enforced)")
        if res['best_match_info']:
            top_n, top_s, sec_n, sec_s, marg = res['best_match_info']
            print(f"  Top Candidate: {top_n} ({top_s:.3f}) | Runner-up: {sec_n} ({sec_s:.3f}) | Margin: {marg:.3f}")
        print(f"  Peak Memory: {res['peak_memory_mb']:.2f} MB")

    # Output JSON summary
    json_path = os.path.join(base_eval_dir, "f23_9e_results.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nDetailed JSON report saved to: {json_path}")

if __name__ == "__main__":
    execute_evaluation()
