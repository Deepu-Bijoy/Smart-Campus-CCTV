import os
import sys
import time
import asyncio
import hashlib
import sqlite3
import numpy as np

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.video import Video
from app.models.track import Track
from app.models.student import Student
from app.models.recognition import StudentRecognitionEvent
from app.models.incident import IncidentPerson
from app.api.v1.violence import analyze_video_for_violence
from sqlalchemy import select

EXPECTED_X3D_HASH = "e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349"
BENCHMARK_VIDEO_ID = "58a574f8-0491-4206-9243-b9761f80898d"

async def run_controlled_validation():
    print("=" * 70)
    print("PHASE F17 CONTROLLED VALIDATION RUN")
    print("=" * 70)

    # 1. Verify Checkpoint and Threshold Integrity
    ckpt_path = os.path.join(settings.STORAGE_DIR, "models", "x3d", "final_x3d_realtime.pt")
    assert os.path.exists(ckpt_path), f"Checkpoint missing at {ckpt_path}"
    with open(ckpt_path, "rb") as f:
        actual_hash = hashlib.sha256(f.read()).hexdigest()
    assert actual_hash == EXPECTED_X3D_HASH, f"Hash mismatch: {actual_hash}"
    print(f"[OK] X3D Checkpoint SHA-256 locked: {actual_hash}")

    assert settings.RECOGNITION_MEDIUM_THRESHOLD == 0.60, "Medium threshold must remain 0.60"
    assert settings.RECOGNITION_HIGH_THRESHOLD == 0.75, "High threshold must remain 0.75"
    from app.pipeline.x3d_violence_detector import X3DViolenceDetector
    detector = X3DViolenceDetector()
    assert detector.threshold == 0.40, "Violence threshold must remain 0.40"
    print(f"[OK] Thresholds locked: Violence={detector.threshold}, Medium={settings.RECOGNITION_MEDIUM_THRESHOLD}, High={settings.RECOGNITION_HIGH_THRESHOLD}")

    # 2. Database Foreign Key Check
    db_path = os.path.join(settings.STORAGE_DIR, "cctv.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("PRAGMA foreign_key_check")
    fk_errors = c.fetchall()
    assert len(fk_errors) == 0, f"Foreign key errors: {fk_errors}"
    print("[OK] PRAGMA foreign_key_check passed with 0 errors.")
    conn.close()

    # 3. Run Violence Pipeline on Benchmark Footage
    t0 = time.time()
    print(f"\nExecuting analyze_video_for_violence on video: {BENCHMARK_VIDEO_ID}...")
    
    async with SessionLocal() as db:
        # Fetch mock admin user for authorization
        u_res = await db.execute(select(Video).filter(Video.id == BENCHMARK_VIDEO_ID))
        video = u_res.scalars().first()
        assert video is not None, f"Video {BENCHMARK_VIDEO_ID} not found in DB!"

        response = await analyze_video_for_violence(
            video_id=BENCHMARK_VIDEO_ID,
            db=db,
            current_user=None  # analyze_video_for_violence accepts current_user=None in internal calls
        )
    
    elapsed = time.time() - t0
    print(f"[OK] Pipeline execution completed in {elapsed:.2f}s.")

    # 4. Analyze Violence Response Structure
    print("\n--- Pipeline Output Inspection ---")
    print(f"Status: {response.status}")
    print(f"Verdict: {response.verdict}")
    print(f"Confidence: {response.overall_confidence}")
    print(f"Segments count: {response.total_segments}")
    assert response.status == "VIOLENCE_DETECTED", f"Expected VIOLENCE_DETECTED, got {response.status}"
    assert response.total_segments >= 1, "Expected at least 1 violence segment"

    # 5. Check Identified Students in API Response
    identified_students = response.identified_students
    print(f"\nRoot identified_students count: {len(identified_students)}")
    for st in identified_students:
        print(f"  - Student: {st.name} | Roll: {st.roll_number} | Sim: {st.similarity_score:.4f} | Conf: {st.confidence} | Track: {st.track_id} | Photo: {st.profile_photo_url}")

    id_names = [st.name for st in identified_students]
    assert "Ashish P" in id_names, f"Ashish P missing from identified_students: {id_names}"
    assert "Anukutty" in id_names, f"Anukutty missing from identified_students: {id_names}"

    # Verify no false matches
    other_students = ["Dipz", "Job Tony", "Mathew Biju", "Arjun Pramod", "Adithya MK", "Rohn Roy"]
    for other in other_students:
        assert other not in id_names, f"FALSE MATCH DETECTED: {other} appeared in identified_students!"
    print(f"[OK] Zero false matches detected against all other enrolled students: {other_students}")

    # 6. Check Segment Involved Students
    seg = response.segments[0]
    print(f"\nSegment 1 (time: {seg.start_time:.1f}s - {seg.end_time:.1f}s, dur: {seg.duration:.1f}s):")
    seg_names = [s.name for s in seg.students if s.name]
    print(f"  Involved students in segment: {seg_names}")
    assert "Ashish P" in seg_names, f"Ashish P missing from segment 1 students: {seg_names}"
    assert "Anukutty" in seg_names, f"Anukutty missing from segment 1 students: {seg_names}"

    # 7. Check Database Records (Tracks, Recognitions, IncidentPersons)
    async with SessionLocal() as db:
        # Check Tracks
        trk_stmt = select(Track).filter(Track.video_id == BENCHMARK_VIDEO_ID)
        trks = (await db.execute(trk_stmt)).scalars().all()
        print(f"\nTracks in DB for video: {len(trks)}")
        
        for t in trks:
            if t.identified_student_id:
                s_obj = (await db.execute(select(Student).filter(Student.id == t.identified_student_id))).scalars().first()
                s_name = s_obj.name if s_obj else "Unknown"
                print(f"  Track DB id: {t.id} | Tracker_id: {t.tracker_id} | Identified: {s_name} | Key Crop: {t.key_frame_path}")

        # Check StudentRecognitionEvents
        rec_stmt = select(StudentRecognitionEvent).filter(StudentRecognitionEvent.video_id == BENCHMARK_VIDEO_ID)
        recs = (await db.execute(rec_stmt)).scalars().all()
        print(f"\nStudentRecognitionEvents saved in DB: {len(recs)}")
        for r in recs:
            s_obj = (await db.execute(select(Student).filter(Student.id == r.student_id))).scalars().first()
            s_name = s_obj.name if s_obj else "Unknown"
            print(f"  Rec Event id: {r.id} | Student: {s_name} | Track: {r.track_id} | Sim: {r.similarity_score:.4f} | Conf: {r.confidence} | Time: {r.timestamp}")

        # Check IncidentPerson associations
        inc_stmt = select(IncidentPerson)
        ips = (await db.execute(inc_stmt)).scalars().all()
        print(f"\nIncidentPerson links in DB: {len(ips)}")
        for ip in ips:
            s_obj = (await db.execute(select(Student).filter(Student.id == ip.student_id))).scalars().first()
            s_name = s_obj.name if s_obj else "Unknown"
            print(f"  IncidentPerson: Student {s_name} | Conf: {ip.confidence:.4f}")

    print("\n" + "=" * 70)
    print("ALL CONTROLLED VALIDATION ASSERTIONS PASSED SUCCESSFULLY!")
    print("=" * 70)
    return True

if __name__ == "__main__":
    asyncio.run(run_controlled_validation())
