import os
import sys
import time
import json
import uuid
import hashlib
import asyncio
from datetime import datetime, timezone
import cv2
import numpy as np

# Ensure backend root is in sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.db.session import SessionLocal
from app.pipeline.x3d_violence_detector import X3DViolenceDetector
from app.api.v1.violence import _track_video_segments_sync, _compile_violence_dossier
from app.models.video import Video
from app.models.camera import Camera
from app.models.student import Student
from app.models.incident import Incident, DetectedEvent, Evidence
from app.models.track import Track, Detection
from app.models.recognition import StudentRecognitionEvent
from app.services.clip_generator import extract_evidence_frame, generate_subclip
from sqlalchemy import select, text

CHECKPOINT_PATH = os.path.join(settings.STORAGE_DIR, "models", "x3d", "final_x3d_realtime.pt")
EXPECTED_HASH = "e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349"
TEST_VIDEO_PATH = os.path.join(settings.STORAGE_DIR, "ec72e1c6-40e1-4b3e-b369-247bd649a4a9.mp4")
if not os.path.exists(TEST_VIDEO_PATH):
    TEST_VIDEO_PATH = os.path.join(settings.STORAGE_DIR, "test_debug_media", "x3d_fight_event.mp4")

async def run_profiling():
    print("=" * 60)
    print("PHASE F14: VIOLENCE DETECTION PERFORMANCE AUDIT")
    print("=" * 60)

    # 1. Checkpoint Verification
    assert os.path.exists(CHECKPOINT_PATH), f"Checkpoint not found at {CHECKPOINT_PATH}"
    actual_hash = hashlib.sha256(open(CHECKPOINT_PATH, "rb").read()).hexdigest()
    print(f"X3D-M Checkpoint: {CHECKPOINT_PATH}")
    print(f"SHA-256: {actual_hash}")
    assert actual_hash == EXPECTED_HASH, f"Hash mismatch! Expected {EXPECTED_HASH}, got {actual_hash}"
    print("SHA-256 Verification: PASSED [MATCH]")

    # 2. Test Video Characteristics
    assert os.path.exists(TEST_VIDEO_PATH), f"Test video not found at {TEST_VIDEO_PATH}"
    cap = cv2.VideoCapture(TEST_VIDEO_PATH)
    fps = cap.get(cv2.CAP_PROP_FPS) or 20.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration = total_frames / fps if fps > 0 else 0.0
    cap.release()

    print(f"Test Video: {TEST_VIDEO_PATH}")
    print(f"  Duration:   {duration:.2f}s")
    print(f"  Frames:     {total_frames}")
    print(f"  FPS:        {fps:.1f}")
    print(f"  Resolution: {width}x{height}")
    print("-" * 60)

    # 3. Profiling Execution
    t_wall_start = time.time()

    # Stage 1: X3D-M Inference
    t_x3d_start = time.time()
    x3d_detector = X3DViolenceDetector()
    t_x3d_load = time.time() - t_x3d_start

    x3d_res = await asyncio.to_thread(
        x3d_detector.detect_violence,
        TEST_VIDEO_PATH,
        window_duration_sec=2.0,
        stride_sec=1.0,
        threshold=0.4,
        context_margin_sec=1.0
    )
    t_x3d_total = time.time() - t_x3d_start

    print(f"[STAGE 1] X3D-M Violence Detection:")
    print(f"  Model Load:            {t_x3d_load:.3f}s")
    print(f"  Preprocessing:         {x3d_res.timings.get('video_preprocessing_sec', 0.0):.3f}s")
    print(f"  Model Inference:       {x3d_res.timings.get('violence_inference_sec', 0.0):.3f}s")
    print(f"  Segment Extraction:    {x3d_res.timings.get('segment_extraction_sec', 0.0):.3f}s")
    print(f"  Total X3D Stage:       {t_x3d_total:.3f}s")
    print(f"  Is Violent:            {x3d_res.is_violent}")
    print(f"  Segments Found:        {len(x3d_res.segments)}")
    for s_idx, s in enumerate(x3d_res.segments):
        print(f"    Segment {s_idx+1}: {s.start_time:.1f}s - {s.end_time:.1f}s (conf: {s.confidence*100:.1f}%)")

    test_video_id = uuid.uuid4()

    # Stage 2: Tracking (YOLOv8 + ByteTrack) & Face Candidate Evaluation
    t_track_start = time.time()
    all_tracks, t_yolo, t_bt = await asyncio.to_thread(
        _track_video_segments_sync,
        TEST_VIDEO_PATH,
        test_video_id,
        x3d_res.segments,
        duration
    )
    t_track_total = time.time() - t_track_start

    print(f"[STAGE 2] YOLOv8 + ByteTrack & Face Sampling:")
    print(f"  YOLO Tracking Loop:    {t_yolo:.3f}s")
    print(f"  ByteTrack Pure Time:   {t_bt:.3f}s")
    print(f"  Total Stage 2 Time:    {t_track_total:.3f}s")
    print(f"  Tracks Extracted:      {len(all_tracks)}")
    total_cand_faces = sum(len(tr.get("candidate_face_crops", [])) for tr in all_tracks.values())
    print(f"  Candidate Face Crops:  {total_cand_faces}")

    # Stage 3: Biometric Student Identification (ArcFace cosine similarity)
    t_arc_start = time.time()
    async with SessionLocal() as db:
        enrolled_db_embeddings = []
        db_emb_res = await db.execute(text("SELECT student_id, embedding FROM student_face_embeddings"))
        for sid_val, raw_emb in db_emb_res.fetchall():
            if not raw_emb:
                continue
            v_arr = np.array(json.loads(raw_emb) if isinstance(raw_emb, str) else raw_emb, dtype=np.float32)
            v_norm = np.linalg.norm(v_arr)
            if v_norm > 0:
                v_arr = v_arr / v_norm
            enrolled_db_embeddings.append((uuid.UUID(str(sid_val)), v_arr))

        all_std_res = await db.execute(select(Student))
        enrolled_students_map = {s.id: s for s in all_std_res.scalars().all()}

        track_identity_cache = {}
        for trk_id, trk_data in all_tracks.items():
            candidate_list = trk_data.get("candidate_face_crops", [])
            matched_by_student = {}
            for cand in candidate_list:
                cand_emb = cand.get("embedding")
                cand_path = cand.get("path")
                sim = 0.0
                best_sid = None
                if cand_emb and enrolled_db_embeddings:
                    emb_arr = np.array(cand_emb, dtype=np.float32)
                    e_norm = np.linalg.norm(emb_arr)
                    if e_norm > 0:
                        emb_arr = emb_arr / e_norm
                    for sid, db_vec in enrolled_db_embeddings:
                        s_sim = float(np.dot(emb_arr, db_vec))
                        if s_sim > sim:
                            sim = s_sim
                            best_sid = sid

                if best_sid and sim >= settings.RECOGNITION_MEDIUM_THRESHOLD:
                    if best_sid not in matched_by_student or sim > matched_by_student[best_sid]["similarity_score"]:
                        student_obj = enrolled_students_map.get(best_sid)
                        if student_obj:
                            matched_by_student[best_sid] = {
                                "student": student_obj,
                                "similarity_score": sim,
                                "confidence": "high" if sim >= settings.RECOGNITION_HIGH_THRESHOLD else "medium",
                                "matched_crop_path": cand_path
                            }
            track_identity_cache[trk_id] = list(matched_by_student.values())

    t_arc_total = time.time() - t_arc_start
    print(f"[STAGE 3] Biometric Matching (ArcFace Vectors):")
    print(f"  Biometric Time:        {t_arc_total:.3f}s")
    for trk_id, id_list in track_identity_cache.items():
        if id_list:
            for item in id_list:
                print(f"    Track {trk_id} -> Student: {item['student'].name} (sim: {item['similarity_score']:.3f}, conf: {item['confidence']})")

    # Stage 4: Evidence Frame and Clip Generation
    t_ev_start = time.time()
    os.makedirs(os.path.join(settings.STORAGE_DIR, "evidence"), exist_ok=True)
    evidence_files = []
    for s_idx, seg in enumerate(x3d_res.segments):
        mid_sec = (seg.start_time + seg.end_time) / 2.0
        frame_filename = f"test_ev_frame_{test_video_id.hex[:8]}_seg{s_idx}.jpg"
        frame_path = os.path.join(settings.STORAGE_DIR, "evidence", frame_filename)
        await asyncio.to_thread(extract_evidence_frame, TEST_VIDEO_PATH, mid_sec, frame_path)
        evidence_files.append(frame_path)

        clip_filename = f"test_clip_{test_video_id.hex[:8]}_seg{s_idx}.mp4"
        clip_path = os.path.join(settings.STORAGE_DIR, "evidence", clip_filename)
        await asyncio.to_thread(generate_subclip, TEST_VIDEO_PATH, seg.start_time, seg.duration, clip_path)
        evidence_files.append(clip_path)

    t_evidence_total = time.time() - t_ev_start
    print(f"[STAGE 4] Evidence Media Generation:")
    print(f"  Evidence Gen Time:     {t_evidence_total:.3f}s")

    from app.models.user import User
    # Stage 5: Database Persistence & Alert Dispatch Mock
    t_db_start = time.time()
    async with SessionLocal() as db:
        # Create disposable video record
        c_res = await db.execute(select(Camera))
        cam = c_res.scalars().first()
        u_res = await db.execute(select(User))
        user_obj = u_res.scalars().first()
        test_video = Video(
            id=test_video_id,
            title="Performance Audit Test Video",
            filename="x3d_fight_event.mp4",
            original_filename="x3d_fight_event.mp4",
            file_path=TEST_VIDEO_PATH,
            status="processing",
            duration=duration,
            width=width,
            height=height,
            fps=fps,
            camera_id=cam.id if cam else None,
            uploaded_by=user_obj.id if user_obj else None
        )
        db.add(test_video)
        await db.commit()

        # Add test incidents and tracks
        for s_idx, seg in enumerate(x3d_res.segments):
            inc_id = uuid.uuid4()
            inc = Incident(
                id=inc_id,
                incident_type="Violence",
                camera_id=cam.id if cam else None,
                confidence=seg.confidence,
                timestamp=datetime.now(timezone.utc),
                explanation=f"X3D Violence {seg.confidence:.2f}"
            )
            db.add(inc)
            ev = DetectedEvent(
                id=uuid.uuid4(),
                video_id=test_video_id,
                camera_id=cam.id if cam else None,
                incident_id=inc_id,
                event_type="VIOLENCE",
                confidence=seg.confidence,
                timestamp=datetime.now(timezone.utc)
            )
            db.add(ev)

        await db.commit()

        # Clean up test records
        await db.execute(text("DELETE FROM detected_events WHERE video_id = :vid").bindparams(vid=str(test_video_id)))
        await db.execute(text("DELETE FROM videos WHERE id = :vid").bindparams(vid=str(test_video_id)))
        await db.commit()

    t_db_total = time.time() - t_db_start
    print(f"[STAGE 5] DB Persistence & Session Handling:")
    print(f"  DB Time:               {t_db_total:.3f}s")

    t_wall_total = time.time() - t_wall_start
    print("-" * 60)
    print(f"TOTAL WALL-CLOCK PIPELINE TIME: {t_wall_total:.3f}s")
    print("=" * 60)

    # Clean up generated test evidence files
    for f in evidence_files:
        if os.path.exists(f):
            try:
                os.remove(f)
            except Exception:
                pass

    crop_dir = os.path.join(settings.STORAGE_DIR, "crops", str(test_video_id))
    if os.path.exists(crop_dir):
        import shutil
        shutil.rmtree(crop_dir, ignore_errors=True)

    return {
        "x3d_time": t_x3d_total,
        "x3d_inference": x3d_res.timings.get("violence_inference_sec", 0.0),
        "yolo_time": t_yolo,
        "bytetrack_time": t_bt,
        "track_total": t_track_total,
        "arcface_time": t_arc_total,
        "evidence_time": t_evidence_total,
        "db_time": t_db_total,
        "wall_total": t_wall_total,
        "is_violent": x3d_res.is_violent,
        "segments_count": len(x3d_res.segments)
    }

if __name__ == "__main__":
    asyncio.run(run_profiling())
