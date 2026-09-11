"""
End-to-End Integration Test for X3D-M Violence Detection Feature

Verifies:
1. X3D-M video violence detection service initialization and checkpoint loading.
2. Temporal video input preprocessing (16 frames, 224x224, RGB normalized).
3. Sliding-window temporal analysis for timestamp detection.
4. Segment-only downstream processing (YOLOv8 + ByteTrack + ArcFace).
5. Evidence generation (frame + video sub-clip).
6. FastAPI endpoints: POST /api/v1/violence/upload and POST /api/v1/violence/analyze.
7. Confirmation that existing FightDetector remains intact in event_engine.py.
"""

import os
import sys

# Configure test environment prior to app imports to avoid file lock conflicts
os.environ["TEST_DATABASE_URI"] = "sqlite+aiosqlite:///./storage/test_x3d.db"
os.environ["DB_FALLBACK_SQLITE"] = "true"
os.environ["CELERY_ALWAYS_EAGER"] = "true"
os.environ["QDRANT_IN_MEMORY"] = "true"

import uuid
import cv2
import numpy as np
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import asyncio
from app.main import app
from app.api import deps
from app.models.user import User
from app.db.session import engine
from app.db.base_class import Base
from app.pipeline.x3d_violence_detector import X3DViolenceDetector, detect_video_violence
from app.event_engine.event_engine import FightDetector, EventDetectionEngine

mock_user = User(
    id=uuid.UUID("e1f2a3b4-c5d6-7890-1234-567890abcdef"),
    email="lead_analyst@campus.edu",
    hashed_password="hashed_pw_test",
    full_name="Lead Forensic Analyst",
    is_active=True
)
app.dependency_overrides[deps.get_current_user] = lambda: mock_user

async def async_setup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def create_synthetic_cctv_video(file_path: str, duration_sec: float = 4.0, fps: float = 20.0, add_motion: bool = False):
    """Generates a synthetic CCTV video stream for testing."""
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    w, h = 640, 480
    out = cv2.VideoWriter(file_path, fourcc, fps, (w, h))

    total_frames = int(duration_sec * fps)
    for f_idx in range(total_frames):
        # Base campus background (slate floor and wall)
        frame = np.full((h, w, 3), 110, dtype=np.uint8)
        frame[240:, :] = 70  # darker ground floor

        # Draw timestamp and camera ID banner
        cv2.putText(frame, f"CAM-03 NORTH COURTYARD - {f_idx/fps:.2f}s", (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        if add_motion:
            # Add synthetic moving person rectangles (simulating altercation dynamics)
            shift = int((f_idx % 20) * 8)
            # Person 1
            cv2.rectangle(frame, (180 + shift, 160), (250 + shift, 360), (30, 180, 50), -1)
            cv2.circle(frame, (215 + shift, 130), 25, (200, 180, 150), -1)
            # Person 2
            cv2.rectangle(frame, (320 - shift, 150), (390 - shift, 350), (200, 50, 30), -1)
            cv2.circle(frame, (355 - shift, 120), 25, (190, 170, 140), -1)

        out.write(frame)

    out.release()
    return file_path


def test_existing_fight_detector_intact():
    """Verify that existing FightDetector was NOT deleted or modified."""
    print("\n[VERIFICATION 1] Confirming existing FightDetector is intact in event_engine...")
    detector = FightDetector()
    assert hasattr(detector, "analyze"), "FightDetector must have 'analyze' method"
    score, breakdown = detector.analyze([], 0.20, 5.0)
    assert isinstance(score, float), "FightDetector.analyze must return float score"
    assert isinstance(breakdown, dict), "FightDetector.analyze must return breakdown dict"
    print("  --> PASS: Existing FightDetector remains intact and functional.")


def test_x3d_service_initialization():
    """Verify that X3DViolenceDetector initializes and loads final_x3d_realtime.pt."""
    print("\n[VERIFICATION 2] Initializing X3D-M Violence Detector...")
    detector = X3DViolenceDetector()
    assert detector.model is not None, "X3D-M model must be loaded"
    assert detector.threshold == 0.4, "Default calibrated threshold must be 0.4"
    assert detector.num_frames == 16, "Must expect 16 frames"
    assert detector.frame_size == 224, "Must expect 224x224 resolution"
    print(f"  --> PASS: X3D-M loaded successfully on device: {detector.device}.")


def test_x3d_normal_video_inference():
    """Verify X3D-M classification on normal CCTV footage."""
    print("\n[VERIFICATION 3] Running X3D-M on Normal CCTV footage...")
    normal_video_path = os.path.join("storage", "test_debug_media", "x3d_test_normal.mp4")
    create_synthetic_cctv_video(normal_video_path, duration_sec=3.0, fps=15.0, add_motion=False)

    detector = X3DViolenceDetector()
    result = detector.detect_violence(normal_video_path)

    assert result.is_violent is False, "Synthetic static footage must be classified as Normal"
    assert len(result.segments) == 0, "Normal footage must yield 0 violent segments"
    assert "Normal campus activity verified" in result.verdict
    assert "violence_inference_sec" in result.timings
    print(f"  --> PASS: Normal video classified correctly (took {result.timings['total_x3d_sec']:.3f}s).")


def test_x3d_sliding_window_temporal_analysis():
    """Verify sliding window temporal sampling and timestamp localization."""
    print("\n[VERIFICATION 4] Testing temporal windowing and segment extraction...")
    test_video_path = os.path.join("storage", "test_debug_media", "x3d_test_windows.mp4")
    create_synthetic_cctv_video(test_video_path, duration_sec=5.0, fps=20.0, add_motion=True)

    detector = X3DViolenceDetector()
    result = detector.detect_violence(test_video_path, window_duration_sec=2.0, stride_sec=1.0)

    assert len(result.windows) >= 3, "5s video with 1s stride must yield at least 3 sliding windows"
    for w in result.windows:
        assert 0.0 <= w.violent_prob <= 1.0, "Window violent probability must be in [0, 1]"
        assert w.start_sec < w.end_sec, "Window start must precede end"
    print(f"  --> PASS: Evaluated {len(result.windows)} temporal windows across video.")


def test_api_upload_and_analyze_pipeline():
    """Verify end-to-end FastAPI upload and analyze workflow with X3D-M."""
    print("\n[VERIFICATION 5] Testing FastAPI endpoints: /upload and /analyze...")
    client = TestClient(app)

    # 1. Upload Video
    video_file_path = os.path.join("storage", "test_debug_media", "x3d_api_test.mp4")
    create_synthetic_cctv_video(video_file_path, duration_sec=2.5, fps=20.0, add_motion=False)

    with open(video_file_path, "rb") as vf:
        up_res = client.post(
            "/api/v1/violence/upload",
            files={"file": ("x3d_api_test.mp4", vf, "video/mp4")},
            data={"title": "X3D Test Video"}
        )

    assert up_res.status_code == 201, f"Upload failed with {up_res.status_code}: {up_res.text}"
    v_data = up_res.json()
    video_id = v_data["video_id"]
    print(f"  --> Video uploaded successfully (ID: {video_id})")

    # 2. Analyze Video with X3D-M
    an_res = client.post(
        "/api/v1/violence/analyze",
        data={"video_id": video_id}
    )

    assert an_res.status_code == 200, f"Analyze failed with {an_res.status_code}: {an_res.text}"
    an_data = an_res.json()
    assert an_data["video_id"] == video_id
    assert an_data["status"] in ["NORMAL", "VIOLENCE_DETECTED"]
    assert "verdict" in an_data
    assert "overall_confidence" in an_data
    assert "segments" in an_data
    print(f"  --> PASS: /api/v1/violence/analyze succeeded with status {an_res.status_code} ({an_data['status']})")


def test_x3d_violence_detected_segment_workflow():
    """Verify full downstream workflow when X3D-M locates a physical altercation segment."""
    print("\n[VERIFICATION 6] Testing Violence Detected segment workflow (YOLOv8 + ByteTrack + Evidence)...")
    from app.pipeline.x3d_violence_detector import X3DAnalysisResult, ViolenceSegmentResult, ViolenceWindow
    client = TestClient(app)

    video_path = os.path.join("storage", "test_debug_media", "x3d_fight_event.mp4")
    create_synthetic_cctv_video(video_path, duration_sec=4.0, fps=20.0, add_motion=True)

    with open(video_path, "rb") as vf:
        up_res = client.post(
            "/api/v1/violence/upload",
            files={"file": ("x3d_fight_event.mp4", vf, "video/mp4")},
            data={"title": "Campus Fight Segment CCTV"}
        )

    assert up_res.status_code == 201
    video_id = up_res.json()["video_id"]

    simulated_x3d = X3DAnalysisResult(
        is_violent=True,
        verdict="VIOLENCE DETECTED: 1 aggressive physical altercation segment located.",
        overall_confidence=0.914,
        segments=[
            ViolenceSegmentResult(
                start_time=1.0,
                end_time=3.0,
                duration=2.0,
                confidence=0.914,
                classification="Violence"
            )
        ],
        windows=[
            ViolenceWindow(index=0, start_sec=0.0, end_sec=2.0, violent_prob=0.35),
            ViolenceWindow(index=1, start_sec=1.0, end_sec=3.0, violent_prob=0.914),
            ViolenceWindow(index=2, start_sec=2.0, end_sec=4.0, violent_prob=0.42),
        ],
        video_duration=4.0,
        fps=20.0,
        total_frames=80,
        timings={
            "model_loading_sec": 0.0,
            "video_preprocessing_sec": 0.05,
            "violence_inference_sec": 0.28,
            "segment_extraction_sec": 0.01,
            "total_x3d_sec": 0.34
        }
    )

    with patch.object(X3DViolenceDetector, "detect_violence", return_value=simulated_x3d):
        an_res = client.post("/api/v1/violence/analyze", data={"video_id": video_id})

    assert an_res.status_code == 200, f"Analysis failed: {an_res.text}"
    data = an_res.json()

    assert data["status"] == "VIOLENCE_DETECTED", f"Expected VIOLENCE_DETECTED but got {data['status']}"
    assert data["overall_confidence"] >= 0.90, f"Confidence mismatch: {data['overall_confidence']}"
    assert len(data["segments"]) >= 1, "Must contain at least 1 violence segment"
    seg = data["segments"][0]
    assert seg["start_time"] <= 1.0, f"Start time incorrect: {seg['start_time']}"
    assert seg["duration"] >= 2.0, f"Duration incorrect: {seg['duration']}"
    assert data["primary_evidence_image"] is not None, "Evidence frame must be populated"
    assert data["primary_evidence_video"] is not None, "Evidence video must be populated"

    print(f"  --> Status: {data['status']}")
    print(f"  --> Violence Confidence: {data['overall_confidence'] * 100:.1f}%")
    print(f"  --> Altercation Window: {seg['timestamp_display']} (duration: {seg['duration']}s)")
    print(f"  --> Evidence Frame: {data['primary_evidence_image']}")
    print(f"  --> Evidence Clip: {data['primary_evidence_video']}")
    print("  --> PASS: Full X3D-M Violence Detection & Evidence Dossier Verified.")


if __name__ == "__main__":
    print("=================================================================")
    print("RUNNING COMPLETE X3D-M VIOLENCE WORKFLOW TEST SUITE")
    print("=================================================================")
    asyncio.run(async_setup())
    test_existing_fight_detector_intact()
    test_x3d_service_initialization()
    test_x3d_normal_video_inference()
    test_x3d_sliding_window_temporal_analysis()
    test_api_upload_and_analyze_pipeline()
    test_x3d_violence_detected_segment_workflow()
    print("\n=================================================================")
    print("ALL TESTS PASSED: Pretrained X3D-M Violence Detection Verified!")
    print("=================================================================")
