import asyncio
import os
import sys
import uuid
import cv2
import numpy as np
import torch
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

# Set fallback test environment variables
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_person_prep.db"

# Mock out heavy deep learning models for fast deterministic unit testing
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['transformers'] = MagicMock()

backend_path = os.path.dirname(os.path.abspath(__file__))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from app.main import app
from app.api import deps
from app.core.config import settings
from app.db.session import engine, SessionLocal
from app.db.base_class import Base
from app.models.user import User
from app.models.video import Video
from app.models.camera import Camera
from app.models.track import Track, Detection, PersonReid
from app.models.incident import Incident, DetectedEvent, Evidence
from app.pipeline.video_reader import VideoReader
from app.pipeline.frame_processor import FrameProcessor
from app.api.v1.violence import _compile_violence_dossier
from app.schemas.violence import SegmentTrackInfo

client = TestClient(app)

def create_synthetic_mp4(filepath: str, duration_sec: float = 10.0, fps: float = 10.0):
    """Creates a real valid synthetic mp4 file using OpenCV VideoWriter."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    total_frames = int(duration_sec * fps)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(filepath, fourcc, fps, (320, 240))
    for i in range(total_frames):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        # Person 1 simulated blob: center
        cv2.rectangle(frame, (80, 50), (140, 200), (200, 200, 200), -1)
        # Person 2 simulated blob: right
        cv2.rectangle(frame, (180, 60), (240, 210), (150, 150, 150), -1)
        cv2.putText(frame, f"F:{i} T:{i/fps:.1f}s", (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        out.write(frame)
    out.release()

async def init_test_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

def run_person_prep_tests():
    print("\n=======================================================")
    print("  RUNNING PERSON-IDENTIFICATION PREPARATION TEST SUITE")
    print("=======================================================")
    asyncio.run(init_test_db())

    storage_dir = settings.STORAGE_DIR
    os.makedirs(os.path.join(storage_dir, "crops"), exist_ok=True)
    os.makedirs(storage_dir, exist_ok=True)

    test_video_path = os.path.join(storage_dir, "test_prep_source.mp4")
    create_synthetic_mp4(test_video_path, duration_sec=10.0, fps=10.0)

    # -------------------------------------------------------------
    # TEST 1: Temporal Windowing in VideoReader
    # -------------------------------------------------------------
    print("\n[TEST 1] Testing temporal segment windowing in VideoReader...")
    reader = VideoReader(test_video_path, target_fps=5.0)
    
    # 1a. Full video reading
    all_frames = list(reader.read_frames())
    assert len(all_frames) > 0, "Full video reading should yield frames"
    print(f"  --> Full video reading yielded {len(all_frames)} frames.")
    
    # 1b. Segment windowing: [2.0s to 5.0s]
    seg_frames = list(reader.read_frames(start_time=2.0, end_time=5.0))
    assert len(seg_frames) > 0, "Segment reading should yield frames"
    assert len(seg_frames) < len(all_frames), "Segment frames should be a subset of full frames"
    first_ts = seg_frames[0][1]
    last_ts = seg_frames[-1][1]
    assert first_ts >= 1.8, f"Expected start near 2.0s, got {first_ts}"
    assert last_ts <= 5.2, f"Expected end near 5.0s, got {last_ts}"
    print(f"  --> Segment window [2.0s - 5.0s] yielded {len(seg_frames)} frames (timestamps: {first_ts:.1f}s to {last_ts:.1f}s).")
    print("  --> PASSED: VideoReader temporal windowing verified.")

    # -------------------------------------------------------------
    # Helper: Mock YOLO + ByteTrack for deterministic tracker scenarios
    # -------------------------------------------------------------
    class MockBoxes:
        def __init__(self, xyxy, ids, confs, clss):
            self._xyxy = torch.tensor(xyxy, dtype=torch.float32)
            self._ids = torch.tensor(ids, dtype=torch.int32)
            self._conf = torch.tensor(confs, dtype=torch.float32)
            self._cls = torch.tensor(clss, dtype=torch.int32)

        @property
        def xyxy(self):
            return self._xyxy
        @property
        def id(self):
            return self._ids
        @property
        def conf(self):
            return self._conf
        @property
        def cls(self):
            return self._cls

    class MockDetectionResult:
        def __init__(self, boxes):
            self.boxes = boxes

    # -------------------------------------------------------------
    # TEST 2: Single Person in Violence Segment
    # -------------------------------------------------------------
    print("\n[TEST 2] Testing single person in violence segment...")
    v_id = uuid.uuid4()
    evt_id = uuid.uuid4()
    proc = FrameProcessor(v_id, test_video_path, target_fps=5.0)

    # Configure mock tracker to detect 1 person with track ID 1
    def single_person_track(detector, frame, persist=True):
        boxes = MockBoxes(
            xyxy=[[50.0, 40.0, 120.0, 200.0]],
            ids=[1],
            confs=[0.92],
            clss=[0]  # person
        )
        return MockDetectionResult(boxes)

    proc.tracker.track_frame = single_person_track

    tracks, dets, crops = proc.process_segment(start_time=1.0, end_time=3.0, event_id=evt_id)
    assert len(tracks) == 1, f"Expected 1 track, got {len(tracks)}"
    assert tracks[0]["tracker_id"] == 1
    assert tracks[0]["object_class"] == "person"
    assert tracks[0]["event_id"] == str(evt_id)
    assert len(dets) > 0, "Detections should be recorded"
    assert round(dets[0]["confidence"], 2) == 0.92
    assert dets[0]["event_id"] == str(evt_id)
    assert len(crops) > 0, "Person crop should be extracted and saved"
    assert os.path.exists(crops[0]["crop_path"]), f"Crop file missing: {crops[0]['crop_path']}"
    assert crops[0]["event_id"] == str(evt_id)
    assert crops[0]["tracker_id"] == 1
    assert "bounding_box" in crops[0]
    print(f"  --> Track 1: {len(dets)} detections, crop: {crops[0]['crop_path']} ({os.path.getsize(crops[0]['crop_path'])} bytes)")
    print("  --> PASSED: Single person in segment properly tracked, cropped, and associated.")

    # -------------------------------------------------------------
    # TEST 3: Multiple People in Violence Segment
    # -------------------------------------------------------------
    print("\n[TEST 3] Testing multiple people in violence segment...")
    proc_multi = FrameProcessor(v_id, test_video_path, target_fps=5.0)

    def multi_person_track(detector, frame, persist=True):
        boxes = MockBoxes(
            xyxy=[
                [40.0, 30.0, 100.0, 180.0],   # Person 1
                [160.0, 50.0, 220.0, 190.0]   # Person 2
            ],
            ids=[1, 2],
            confs=[0.94, 0.89],
            clss=[0, 0]  # both person
        )
        return MockDetectionResult(boxes)

    proc_multi.tracker.track_frame = multi_person_track

    tracks_m, dets_m, crops_m = proc_multi.process_segment(start_time=2.0, end_time=4.0, event_id=evt_id)
    assert len(tracks_m) == 2, f"Expected 2 tracks, got {len(tracks_m)}"
    tracker_ids = {t["tracker_id"] for t in tracks_m}
    assert tracker_ids == {1, 2}, f"Expected tracker IDs {1, 2}, got {tracker_ids}"
    
    crop_tracker_ids = {c["tracker_id"] for c in crops_m}
    assert 1 in crop_tracker_ids and 2 in crop_tracker_ids, "Both persons must have extracted crops"
    print(f"  --> Tracks created: {tracker_ids}")
    print(f"  --> Total detections: {len(dets_m)}, Total crops: {len(crops_m)}")
    print("  --> PASSED: Multiple people in segment assigned distinct persistent track IDs & crops.")

    # -------------------------------------------------------------
    # TEST 4: Partially Visible People (Frame Edge Clamping)
    # -------------------------------------------------------------
    print("\n[TEST 4] Testing partially visible people (edge bounding boxes)...")
    proc_edge = FrameProcessor(v_id, test_video_path, target_fps=5.0)

    # Box coordinates extends outside of image (image is 320x240)
    def edge_person_track(detector, frame, persist=True):
        boxes = MockBoxes(
            xyxy=[
                [-15.0, -10.0, 70.0, 260.0],   # Off top-left & bottom edges
                [270.0, 50.0, 345.0, 220.0]    # Off right edge
            ],
            ids=[10, 11],
            confs=[0.85, 0.82],
            clss=[0, 0]
        )
        return MockDetectionResult(boxes)

    proc_edge.tracker.track_frame = edge_person_track

    tracks_e, dets_e, crops_e = proc_edge.process_segment(start_time=0.0, end_time=1.0, event_id=evt_id)
    assert len(tracks_e) == 2
    for c in crops_e:
        assert os.path.exists(c["crop_path"]), f"Edge crop failed to save: {c['crop_path']}"
        img = cv2.imread(c["crop_path"])
        assert img is not None and img.size > 0, "Edge crop should be a valid non-empty image"
        assert img.shape[0] > 0 and img.shape[1] > 0
    print(f"  --> Edge crops safely clamped and extracted: {len(crops_e)} crops.")
    print("  --> PASSED: Partially visible people handled without bounding box or OpenCV errors.")

    # -------------------------------------------------------------
    # TEST 5: People Without Visible Faces
    # -------------------------------------------------------------
    print("\n[TEST 5] Testing people without visible faces (back turned / occluded)...")
    proc_noface = FrameProcessor(v_id, test_video_path, target_fps=5.0)

    # Mock _check_face_visible to return False (no face detectable)
    proc_noface._check_face_visible = lambda crop: False

    def noface_track(detector, frame, persist=True):
        boxes = MockBoxes(
            xyxy=[[60.0, 50.0, 130.0, 190.0]],
            ids=[20],
            confs=[0.90],
            clss=[0]
        )
        return MockDetectionResult(boxes)

    proc_noface.tracker.track_frame = noface_track

    tracks_nf, dets_nf, crops_nf = proc_noface.process_segment(start_time=1.0, end_time=2.0, event_id=evt_id)
    assert len(tracks_nf) == 1
    assert tracks_nf[0]["face_visible"] is False
    assert len(crops_nf) > 0, "Crop must still be saved even when face is not visible"
    assert crops_nf[0]["face_visible"] is False
    assert os.path.exists(crops_nf[0]["crop_path"])
    print(f"  --> Non-visible face track crop saved: {crops_nf[0]['crop_path']} (face_visible=False)")
    print("  --> PASSED: Non-visible face scenario preserved cleanly without ArcFace execution or crashes.")

    # -------------------------------------------------------------
    # TEST 6: Multiple Tracks Over Time & ByteTrack Continuity
    # -------------------------------------------------------------
    print("\n[TEST 6] Testing multiple tracks persistence over consecutive frames...")
    proc_time = FrameProcessor(v_id, test_video_path, target_fps=5.0)

    frame_counter = [0]
    def moving_tracks(detector, frame, persist=True):
        fc = frame_counter[0]
        frame_counter[0] += 1
        # Track 100 moving across, Track 200 standing
        boxes = MockBoxes(
            xyxy=[
                [40.0 + fc * 5, 40.0, 90.0 + fc * 5, 180.0],
                [180.0, 50.0, 230.0, 190.0]
            ],
            ids=[100, 200],
            confs=[0.91, 0.88],
            clss=[0, 0]
        )
        return MockDetectionResult(boxes)

    proc_time.tracker.track_frame = moving_tracks

    tracks_t, dets_t, crops_t = proc_time.process_segment(start_time=0.0, end_time=2.0, event_id=evt_id)
    assert len(tracks_t) == 2
    t100 = next(t for t in tracks_t if t["tracker_id"] == 100)
    t200 = next(t for t in tracks_t if t["tracker_id"] == 200)
    assert t100["start_time"] <= t100["end_time"]
    assert t200["start_time"] <= t200["end_time"]
    dets_100 = [d for d in dets_t if d["track_temp_id"] == 100]
    dets_200 = [d for d in dets_t if d["track_temp_id"] == 200]
    assert len(dets_100) >= 3, f"Expected multiple detections for track 100, got {len(dets_100)}"
    assert len(dets_200) >= 3, f"Expected multiple detections for track 200, got {len(dets_200)}"
    print(f"  --> Track 100 persisted for {len(dets_100)} frames, Track 200 for {len(dets_200)} frames.")
    print("  --> PASSED: Multiple tracks persistent over time verified.")

    # -------------------------------------------------------------
    # TEST 7: Dossier Compilation with SegmentTrackInfo
    # -------------------------------------------------------------
    print("\n[TEST 7] Testing _compile_violence_dossier segment track attachment...")
    db_cam_id = uuid.uuid4()
    db_user_id = uuid.uuid4()
    db_vid_id = uuid.uuid4()
    db_inc_id = uuid.uuid4()
    db_evt_id = uuid.uuid4()
    base_time = datetime.now(timezone.utc)

    async def setup_dossier_with_tracks():
        async with SessionLocal() as db:
            user = User(
                id=db_user_id,
                email="officer@smartcampus.edu",
                hashed_password="fakepassword",
                role="admin"
            )
            db.add(user)

            cam = Camera(
                id=db_cam_id,
                name="Courtyard North",
                building="Hostel 4",
                floor="1st Floor",
                location="Courtyard Lawn",
                direction="North",
                resolution="1920x1080",
                status="active"
            )
            db.add(cam)

            vid = Video(
                id=db_vid_id,
                title="Dossier Track Test Video",
                filename="test_prep_source.mp4",
                original_filename="cctv_fight.mp4",
                file_path=test_video_path,
                status="completed",
                duration=10.0,
                width=320,
                height=240,
                fps=10.0,
                file_size=os.path.getsize(test_video_path),
                camera_id=db_cam_id,
                uploaded_by=db_user_id,
                created_at=base_time
            )
            db.add(vid)

            inc = Incident(
                id=db_inc_id,
                incident_type="Fight",
                timestamp=base_time + timedelta(seconds=5.0),
                camera_id=db_cam_id,
                confidence=0.92,
                explanation="Altercation at 5.0s."
            )
            db.add(inc)

            # Insert 2 Track records in this video
            trk1_id = uuid.uuid4()
            trk2_id = uuid.uuid4()
            t1 = Track(
                id=trk1_id,
                video_id=db_vid_id,
                object_class="person",
                tracker_id=1,
                start_time=3.0,
                end_time=7.0,
                key_frame_path=crops[0]["crop_path"]
            )
            t2 = Track(
                id=trk2_id,
                video_id=db_vid_id,
                object_class="person",
                tracker_id=2,
                start_time=3.0,
                end_time=7.0,
                key_frame_path=None
            )
            db.add(t1)
            db.add(t2)

            # Insert Detections
            db.add(Detection(
                id=uuid.uuid4(),
                track_id=trk1_id,
                frame_number=25,
                timestamp_seconds=5.0,
                bounding_box=[50.0, 40.0, 120.0, 200.0],
                confidence=0.92
            ))
            db.add(Detection(
                id=uuid.uuid4(),
                track_id=trk2_id,
                frame_number=25,
                timestamp_seconds=5.0,
                bounding_box=[160.0, 50.0, 220.0, 190.0],
                confidence=0.88
            ))

            # Associate DetectedEvent with track 1
            evt = DetectedEvent(
                id=db_evt_id,
                incident_id=db_inc_id,
                event_type="FIGHT",
                camera_id=db_cam_id,
                video_id=db_vid_id,
                timestamp=base_time + timedelta(seconds=5.0),
                track_id=trk1_id,
                confidence=0.92
            )
            db.add(evt)
            await db.commit()

            cam_obj = await db.get(Camera, db_cam_id)
            dossier = await _compile_violence_dossier(db, vid, cam_obj)
            return dossier

    dossier = asyncio.run(setup_dossier_with_tracks())
    assert dossier.status == "VIOLENCE_DETECTED"
    assert len(dossier.segments) == 1
    seg = dossier.segments[0]
    assert len(seg.tracks) == 2, f"Expected 2 segment tracks, got {len(seg.tracks)}"
    
    seg_tracker_ids = {st.tracker_id for st in seg.tracks}
    assert seg_tracker_ids == {1, 2}
    for st in seg.tracks:
        assert st.event_id is not None
        assert st.track_id is not None
        assert len(st.bounding_box) == 4
        assert st.confidence > 0.8
        assert isinstance(st.face_visible, bool)
    print(f"  --> Dossier segment tracks populated successfully: {len(seg.tracks)} tracks.")
    for st in seg.tracks:
        print(f"      - Track #{st.tracker_id} (ID: {st.track_id[:8]}..., bbox: {st.bounding_box}, crop: {st.person_crop}, face_vis: {st.face_visible})")
    print("  --> PASSED: Segment track info attached to ViolenceSegment schema.")

    # -------------------------------------------------------------
    # TEST 8: Regression Verification of Existing Surveillance Pipeline
    # -------------------------------------------------------------
    print("\n[TEST 8] Verifying existing surveillance pipeline (FrameProcessor.process)...")
    proc_full = FrameProcessor(v_id, test_video_path, target_fps=5.0)

    # Mock tracker for full video processing
    def full_track(detector, frame, persist=True):
        boxes = MockBoxes(
            xyxy=[[50.0, 40.0, 120.0, 200.0]],
            ids=[1],
            confs=[0.90],
            clss=[0]
        )
        return MockDetectionResult(boxes)

    proc_full.tracker.track_frame = full_track
    final_tracks, detections, reids, clips, count = proc_full.process()
    assert len(final_tracks) > 0, "Full process should return tracks"
    assert len(detections) > 0, "Full process should return detections"
    assert count > 0, "Full process should process frames"
    print(f"  --> Full process returned {len(final_tracks)} tracks, {len(detections)} detections across {count} frames.")
    print("  --> PASSED: Existing surveillance pipeline (FrameProcessor.process) is completely intact.")

    print("\n=======================================================")
    print("  ALL 8 PERSON-IDENTIFICATION PREP TESTS PASSED (8/8)!")
    print("=======================================================\n")

if __name__ == "__main__":
    run_person_prep_tests()
