import asyncio
import os
import sys

backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.db.session import SessionLocal
from app.api.v1.investigations import unified_search, UnifiedSearchRequest

async def test_f5_fight_investigation_search():
    async with SessionLocal() as db:
        # 1. Search for 'Fight'
        req = UnifiedSearchRequest(query="Fight")
        res = await unified_search(req, db, None)

        assert res["query_type"] == "incident", f"Expected query_type 'incident', got {res['query_type']}"
        results = res["results"]
        assert len(results) > 0, "Expected at least 1 incident result for 'Fight'"

        # Find the incident from the uploaded violence video
        target_incidents = [
            r for r in results 
            if r.get("source_video") == "WhatsApp Video 2026-07-27 at 10.29.42 PM.mp4"
        ]

        assert len(target_incidents) >= 1, (
            "Expected violence incident from 'WhatsApp Video 2026-07-27 at 10.29.42 PM.mp4' to be returned."
        )

        for inc in target_incidents:
            print(f"Verified Incident: {inc['id']}")
            print(f"  Title: {inc['title']}")
            print(f"  Source Video: {inc['source_video']}")
            print(f"  Detected At: {inc['detected_at']}")
            print(f"  Interval: {inc['incident_interval']}")
            print(f"  Camera: {inc['camera']}")
            
            # Verify video-relative start timing (e.g. 00:00:06 or 00:00:01)
            assert inc['detected_at'] in ["00:00:06", "00:00:01"], (
                f"Expected start timestamp '00:00:06' or '00:00:01', got: {inc['detected_at']}"
            )
            assert inc['detected_at'] not in ["00:00:09.500", "00:00:04.000"], (
                f"Keyframe midpoint timestamp should NOT be used as incident start time, got {inc['detected_at']}"
            )

            # Verify confirmed students
            students = inc.get("students", [])
            assert len(students) >= 1, "Expected confirmed students associated with incident."
            student_names = [s["name"] for s in students]
            print(f"  Students: {student_names}")
            assert "Anukutty" in student_names or "Ashish P" in student_names, (
                f"Expected Anukutty or Ashish P in students, got: {student_names}"
            )

            # Verify academic fields are populated from student records
            for s in students:
                assert s.get("name"), "Student name missing"
                assert s.get("roll_number"), f"Student roll number missing for {s['name']}"
                assert s.get("roll_number") in ["30", "15"], f"Unexpected roll number {s.get('roll_number')}"
                assert s.get("class") or s.get("programme"), f"Academic class missing for {s['name']}"
                assert s.get("department"), f"Academic department missing for {s['name']}"
                assert s.get("photo_url") and "/storage/" in s.get("photo_url"), (
                    f"Student photo URL missing or invalid: {s.get('photo_url')}"
                )

        # 2. Verify Deduplication
        incident_ids = [r["id"] for r in results if r.get("id")]
        assert len(incident_ids) == len(set(incident_ids)), "Found duplicate incident IDs in results!"

        # Verify signature deduplication
        sigs = [
            (r.get("source_video"), r.get("detected_at"), r.get("incident_interval"))
            for r in results
            if r.get("source_video") and r.get("detected_at")
        ]
        assert len(sigs) == len(set(sigs)), "Found duplicate (source_video, detected_at, interval) matches!"

        print("\n[SUCCESS] Phase F5 backend search verification passed!")

if __name__ == "__main__":
    asyncio.run(test_f5_fight_investigation_search())
