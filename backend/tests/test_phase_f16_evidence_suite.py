import os
import cv2
import json
import uuid
import pytest
import numpy as np
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models.student import Student
from app.models.video import Video
from app.models.track import Track, Detection, PersonReid
from app.models.recognition import StudentRecognitionEvent
from app.services.evidence_manager import (
    resolve_student_track_evidence,
    generate_full_frame_evidence,
    get_or_create_general_evidence_frame,
    format_seconds_to_hhmmss,
    normalize_storage_url,
    draw_bounding_box_overlay
)
from app.api.v1.investigations import search_identity, search_appearance, IdentitySearchRequest, AppearanceSearchRequest
from app.models.user import User


@pytest.mark.anyio
async def test_1_recognized_student_valid_evidence_frame():
    """Test 1: A recognized student with a valid evidence frame."""
    async with SessionLocal() as db:
        res = await db.execute(select(Student).filter(Student.name.like("%Anukutty%")))
        student = res.scalars().first()
        assert student is not None, "Anukutty must exist in students database"

        u_res = await db.execute(select(User))
        user = u_res.scalars().first()

        req = IdentitySearchRequest(query="Find Anukutty")
        id_res = await search_identity(req, db, user)

        assert id_res["type"] == "identity"
        assert id_res["student"]["name"] == student.name
        appearances = id_res["appearances"]
        assert len(appearances) >= 1, "Should find at least 1 appearance"

        # Check the first appearance
        app0 = appearances[0]
        evidence = app0["evidence"]
        img_url = evidence.get("image")
        assert img_url is not None, "Evidence screenshot must not be None"
        assert img_url.startswith("/storage/evidence/"), f"Image url must be in /storage/evidence/: {img_url}"

        # Verify file exists on disk
        clean_rel = img_url.lstrip("/")
        local_path = os.path.join(".", clean_rel) if os.path.exists(os.path.join(".", clean_rel)) else os.path.join("storage", "evidence", os.path.basename(clean_rel))
        assert os.path.exists(local_path), f"Evidence image file must exist on disk at {local_path}"

        # Verify image aspect ratio and valid dimensions
        img = cv2.imread(local_path)
        assert img is not None, "Image must be readable by OpenCV"
        h, w = img.shape[:2]
        assert h == 850 and w == 478, f"Expected portrait 478x850, got {w}x{h}"

        # Verify timestamp is NOT 00:00:00 (the back crop bug)
        assert app0["timestamp"] in ["00:00:11", "00:00:12"], f"Expected timestamp around 00:00:11, got {app0['timestamp']}"

        # Verify person crop is offered separately
        assert evidence.get("person_crop") is not None, "Companion person crop must be offered separately"


@pytest.mark.anyio
async def test_2_two_detections_same_student_different_timestamps():
    """Test 2: Two detections of the same student at different timestamps."""
    async with SessionLocal() as db:
        res = await db.execute(select(Student).filter(Student.name.like("%Anukutty%")))
        student = res.scalars().first()
        u_res = await db.execute(select(User))
        user = u_res.scalars().first()

        req = IdentitySearchRequest(query="Find Anukutty")
        id_res = await search_identity(req, db, user)
        appearances = id_res["appearances"]

        # Filter appearances in video b9065649 (has Track 1 at ~11s and Track 2 at ~28s)
        b9_apps = [a for a in appearances if "b9065649" in (a.get("video_id") or "")]
        assert len(b9_apps) >= 2, f"Should have at least 2 detections in video b9065649, found {len(b9_apps)}"

        timestamps = [a["timestamp"] for a in b9_apps]
        assert "00:00:12" in timestamps or "00:00:11" in timestamps
        assert "00:00:28" in timestamps
        assert len(set(timestamps)) >= 2, "Timestamps must be distinct"

        # Evidence images must be distinct files
        images = [a["evidence"]["image"] for a in b9_apps]
        assert len(set(images)) == len(images), "Evidence frames for different detections must be distinct"


@pytest.mark.anyio
async def test_3_different_tracks_within_same_video():
    """Test 3: Different tracks within the same video."""
    async with SessionLocal() as db:
        res = await db.execute(select(Student).filter(Student.name.like("%Anukutty%")))
        student = res.scalars().first()
        u_res = await db.execute(select(User))
        user = u_res.scalars().first()

        req = IdentitySearchRequest(query="Find Anukutty")
        id_res = await search_identity(req, db, user)
        appearances = id_res["appearances"]

        b9_apps = [a for a in appearances if "b9065649" in (a.get("video_id") or "")]
        track_ids = [a["track_id"] for a in b9_apps]
        assert len(set(track_ids)) >= 2, f"Expected distinct tracks, got {track_ids}"
        assert "39d600ca-292f-4e6a-a1fc-e54a2a452fbb" in track_ids
        assert "e5553fd8-65dd-4b88-a25c-5d3880c61f24" in track_ids


@pytest.mark.anyio
async def test_4_detections_from_different_videos():
    """Test 4: Detections from different videos."""
    async with SessionLocal() as db:
        res = await db.execute(select(Student).filter(Student.name.like("%Anukutty%")))
        student = res.scalars().first()
        u_res = await db.execute(select(User))
        user = u_res.scalars().first()

        req = IdentitySearchRequest(query="Find Anukutty")
        id_res = await search_identity(req, db, user)
        appearances = id_res["appearances"]

        video_ids = list({a["video_id"] for a in appearances if a.get("video_id")})
        assert len(video_ids) >= 2, f"Expected appearances from at least 2 videos, got {video_ids}"
        assert any("ec72e1c6" in vid for vid in video_ids), "ec72e1c6 must be present"
        assert any("b9065649" in vid for vid in video_ids), "b9065649 must be present"


@pytest.mark.anyio
async def test_5_missing_evidence_files():
    """Test 5: Missing evidence files fallback behavior."""
    async with SessionLocal() as db:
        res = await db.execute(select(Student).filter(Student.name.like("%Anukutty%")))
        student = res.scalars().first()

        # Create dummy video pointing to nonexistent file
        dummy_video = Video(
            id=uuid.uuid4(),
            filename="missing_test.mp4",
            original_filename="missing_test.mp4",
            file_path="storage/non_existent_video_12345.mp4"
        )
        dummy_track = Track(
            id=uuid.uuid4(),
            video_id=dummy_video.id,
            object_class="person",
            tracker_id=999,
            start_time=15.0,
            end_time=20.0,
            key_frame_path=None
        )

        dummy_event = StudentRecognitionEvent(
            id=uuid.uuid4(),
            track_id=dummy_track.id,
            student_id=student.id,
            video_id=dummy_video.id,
            similarity_score=0.75,
            confidence="high"
        )

        # Resolve evidence with missing video
        evidence_data = await resolve_student_track_evidence(
            db, dummy_video, dummy_track, student, [dummy_event]
        )

        # Verify fallback handling
        assert evidence_data is not None
        # Must NEVER substitute student enrollment portrait
        enrollment_photos = [p.photo_path for p in student.photos] if student.photos else []
        assert evidence_data.get("evidence_screenshot") not in enrollment_photos
        assert evidence_data.get("person_crop") not in enrollment_photos


@pytest.mark.anyio
async def test_6_detection_with_no_reliable_student_identity():
    """Test 6: A detection with no reliable student identity."""
    async with SessionLocal() as db:
        u_res = await db.execute(select(User))
        user = u_res.scalars().first()

        req = AppearanceSearchRequest(query="person in black shirt")
        app_res = await search_appearance(req, db, user)

        assert app_res["type"] == "appearance"
        assert isinstance(app_res["results"], list)
        for item in app_res["results"]:
            if item.get("identity_status") != "Identified":
                # Ensure no student identity fabricated
                assert item.get("student") is None


def test_7_portrait_and_landscape_source_videos():
    """Test 7: Portrait and landscape source videos preserve source aspect ratio."""
    out_dir = "storage/evidence"
    os.makedirs(out_dir, exist_ok=True)

    # 1. Test Portrait image
    portrait_img = np.zeros((850, 478, 3), dtype=np.uint8)
    portrait_boxed = draw_bounding_box_overlay(
        portrait_img.copy(),
        [35.0, 320.0, 470.0, 840.0],
        label="Portrait Test"
    )
    assert portrait_boxed.shape == (850, 478, 3), "Portrait aspect ratio must remain exactly 478x850"

    # 2. Test Landscape synthetic image (1280x720)
    landscape_img = np.zeros((720, 1280, 3), dtype=np.uint8)
    landscape_boxed = draw_bounding_box_overlay(
        landscape_img.copy(),
        [100.0, 50.0, 600.0, 700.0],
        label="Landscape Test"
    )
    assert landscape_boxed.shape == (720, 1280, 3), "Landscape aspect ratio must remain exactly 1280x720"

    # Verify save & load
    p_path = os.path.join(out_dir, "test_phase_f16_portrait.jpg")
    l_path = os.path.join(out_dir, "test_phase_f16_landscape.jpg")
    cv2.imwrite(p_path, portrait_boxed)
    cv2.imwrite(l_path, landscape_boxed)

    p_read = cv2.imread(p_path)
    l_read = cv2.imread(l_path)
    assert p_read.shape == (850, 478, 3)
    assert l_read.shape == (720, 1280, 3)
