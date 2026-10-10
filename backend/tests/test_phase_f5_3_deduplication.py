import asyncio
import os
import sys

backend_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.db.session import SessionLocal
from app.api.v1.investigations import (
    unified_search, 
    search_identity, 
    search_appearance,
    UnifiedSearchRequest, 
    IdentitySearchRequest,
    AppearanceSearchRequest,
    _format_seconds_to_hhmmss
)
from app.models.user import User

async def run_phase_f5_3_tests():
    print("============================================================")
    print("RUNNING PHASE F5.3 PERSON SEARCH DEDUPLICATION TEST SUITE")
    print("============================================================\n")

    async with SessionLocal() as db:
        user = User(email="admin@test.com", is_active=True)

        # -------------------------------------------------------------
        # TEST 1: Helper function format_seconds_to_hhmmss
        # -------------------------------------------------------------
        print("--- TEST 1: Video-Relative Timestamp Formatting ---")
        assert _format_seconds_to_hhmmss(0.0) == "00:00:00"
        assert _format_seconds_to_hhmmss(9.65) == "00:00:10"
        assert _format_seconds_to_hhmmss(65.0) == "00:01:05"
        assert _format_seconds_to_hhmmss(3665.0) == "01:01:05"
        assert _format_seconds_to_hhmmss(None) == "00:00:00"
        print("[OK] Video-relative timestamp formatting verified.\n")

        # -------------------------------------------------------------
        # TEST 2: Direct Identity Search for Job Tony
        # -------------------------------------------------------------
        print("--- TEST 2: Deduplication by Video & Camera in search_identity ---")
        id_req = IdentitySearchRequest(query="Job Tony")
        id_res = await search_identity(id_req, db, user)

        assert id_res["type"] == "identity"
        student = id_res["student"]
        assert student is not None, "Expected student profile for Job Tony"
        assert student["name"] == "Job Tony"
        assert student["roll_number"] == "100"
        assert student["programme"] == "B.Tech" or student["class"] == "B.Tech"
        assert student["department"] == "Computer Science"
        assert student["semester"] == 7
        assert student["year"] == 4
        assert student["section"] == "A"
        assert student["photo_url"] and "/storage/students/" in student["photo_url"]

        appearances = id_res["appearances"]
        # In our database, Job Tony has detections across 2 videos (14 detections in video 1, 1 in video 2)
        # Deduplication must reduce this to exactly 2 appearances!
        print(f"Total deduplicated appearances: {len(appearances)}")
        assert len(appearances) == 2, f"Expected exactly 2 deduplicated appearances, got {len(appearances)}"

        # Appearance 1: Video 1 (WhatsApp Video 2026-10-10 at 9.45.52 AM.mp4)
        app1 = appearances[0]
        print(f"Appearance 1: video={app1['source_video']}, time={app1['timestamp']}, thumb={app1['evidence']['image']}")
        assert app1["timestamp"] == "00:00:00", f"Expected earliest timestamp 00:00:00, got {app1['timestamp']}"
        assert app1["source_video"] == "WhatsApp Video 2026-10-10 at 9.45.52 AM.mp4"
        assert app1["evidence"]["image"] and "1_0_a23abd.jpg" in app1["evidence"]["image"]
        assert app1["evidence"]["video"] and "/storage/" in app1["evidence"]["video"]

        # Appearance 2: Video 2 (video_2026-10-10_11-04-28.mp4)
        app2 = appearances[1]
        print(f"Appearance 2: video={app2['source_video']}, time={app2['timestamp']}, thumb={app2['evidence']['image']}")
        assert app2["timestamp"] == "00:00:10", f"Expected earliest timestamp 00:00:10, got {app2['timestamp']}"
        assert app2["source_video"] == "video_2026-10-10_11-04-28.mp4"
        assert app2["evidence"]["image"] and "1_288_12d40e.jpg" in app2["evidence"]["image"]

        # Ensure no wall-clock / DB created_at timestamp format (e.g. '2026-10-10') in timestamp
        for app in appearances:
            assert "-" not in app["timestamp"], f"Timestamp should be HH:MM:SS, not datetime: {app['timestamp']}"
            assert len(app["timestamp"].split(":")) == 3, f"Timestamp format invalid: {app['timestamp']}"

        print("[OK] search_identity deduplication and earliest timestamp verified.\n")

        # -------------------------------------------------------------
        # TEST 3: Unified Search for Job Tony (Router & Card Metadata)
        # -------------------------------------------------------------
        print("--- TEST 3: Unified Search Pipeline for 'Job Tony' ---")
        uni_req = UnifiedSearchRequest(query="Job Tony")
        uni_res = await unified_search(uni_req, db, user)

        assert uni_res["query_type"] == "identity", f"Expected query_type 'identity', got {uni_res['query_type']}"
        results = uni_res["results"]
        assert len(results) == 2, f"Expected exactly 2 results for Job Tony across the 2 videos, got {len(results)}"

        # Check fields of each result card
        for r in results:
            assert r["title"] == "Student Identified — Job Tony"
            assert r["incident_type"] == "Student Identified"
            assert r["source_video"] in [
                "WhatsApp Video 2026-10-10 at 9.45.52 AM.mp4",
                "video_2026-10-10_11-04-28.mp4"
            ]
            assert r["detected_at"] in ["00:00:00", "00:00:10"]
            assert r["first_detection_timestamp"] in ["00:00:00", "00:00:10"]
            assert r["student"]["name"] == "Job Tony"
            assert r["student"]["roll_number"] == "100"
            assert r["camera"] and "Gate" in r["camera"]
            assert r["evidence"]["image"] and "/storage/crops/" in r["evidence"]["image"]
            assert r["evidence"]["video"] and "/storage/" in r["evidence"]["video"]

        print("[OK] Unified search returns properly enriched deduplicated cards.\n")

        # -------------------------------------------------------------
        # TEST 4: Scoped Camera Search
        # -------------------------------------------------------------
        print("--- TEST 4: Scoped Camera Filter for Job Tony ---")
        # Find camera_id for GateA
        cam_id = app1.get("video_id") # Test with camera or specific query
        scoped_req = UnifiedSearchRequest(query="Job Tony", camera_id="0bd04cfb-4ce2-4db7-a526-a8550aea8940")
        scoped_res = await unified_search(scoped_req, db, user)
        # Even with camera scope, each video appearance appears once
        for r in scoped_res["results"]:
            assert r["student"]["name"] == "Job Tony"
        print(f"[OK] Scoped search returned {len(scoped_res['results'])} valid results.\n")

        # -------------------------------------------------------------
        # TEST 5: Preserve Distinct Incidents in 'Fight' Search
        # -------------------------------------------------------------
        print("--- TEST 5: Verify Incident Search (Fight) Preserves Distinct Incidents ---")
        fight_req = UnifiedSearchRequest(query="Fight")
        fight_res = await unified_search(fight_req, db, user)

        assert fight_res["query_type"] == "incident"
        fight_results = fight_res["results"]
        assert len(fight_results) > 1, f"Expected multiple distinct incidents, got {len(fight_results)}"

        # Verify incident IDs are unique (no duplicates of the same incident)
        inc_ids = [r["id"] for r in fight_results if r.get("id")]
        assert len(inc_ids) == len(set(inc_ids)), "Found duplicate incident IDs in fight results!"

        # Verify multiple different timestamps exist among fight incidents (no over-deduplication)
        timestamps = {r.get("detected_at") for r in fight_results if r.get("detected_at")}
        assert len(timestamps) > 1, f"Expected distinct timestamps for fight incidents, got: {timestamps}"
        print(f"[OK] Fight search preserved {len(fight_results)} distinct incidents across {len(timestamps)} time intervals.\n")

    print("============================================================")
    print("ALL PHASE F5.3 TESTS PASSED SUCCESSFULLY!")
    print("============================================================\n")

if __name__ == "__main__":
    asyncio.run(run_phase_f5_3_tests())
