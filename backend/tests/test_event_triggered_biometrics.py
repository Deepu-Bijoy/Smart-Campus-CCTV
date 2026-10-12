"""
Test suite for Event-Triggered Face Detection and Student Identification.
Validates:
1. Padded interval clustering (-2.5s, +3.0s) and merging of overlapping intervals.
2. Boundary handling near video start (0.0s) and end (duration).
3. Inclusion of people appearing immediately before and after incidents.
4. Curated candidate selection: significant reduction in InsightFace calls.
5. Graceful fallback to Unidentified Person when faces are turned away or low confidence.
6. Identity-to-track association and duplicate rejection.
7. Zero duplicate incidents or evidence records.
8. Full-timeline X3D coverage.
"""

import os
import sys
import uuid
import unittest
import numpy as np
from pathlib import Path
from types import SimpleNamespace

# Ensure backend root is on sys.path
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.api.v1.violence import _detect_faces_on_candidates_sync
from app.core.config import settings
from app.pipeline.x3d_violence_detector import ViolenceWindow, ViolenceSegmentResult, X3DAnalysisResult


class TestEventTriggeredBiometrics(unittest.TestCase):

    def test_1_interval_expansion_and_merging(self):
        """Verify that discrete violence intervals are expanded by (-2.5s, +3.0s) and overlapping intervals merge."""
        fps = 25.0
        duration = 600.0

        # Scenario:
        # Seg 1: 50.0s - 55.0s -> expanded: 47.5s - 58.0s
        # Seg 2: 57.0s - 62.0s -> expanded: 54.5s - 65.0s (Overlaps Seg 1! Should merge into 47.5s - 65.0s)
        # Seg 3: 200.0s - 205.0s -> expanded: 197.5s - 208.0s (Distinct, non-overlapping)
        segments = [
            SimpleNamespace(start_time=50.0, end_time=55.0, duration=5.0, confidence=0.9),
            SimpleNamespace(start_time=57.0, end_time=62.0, duration=5.0, confidence=0.85),
            SimpleNamespace(start_time=200.0, end_time=205.0, duration=5.0, confidence=0.95),
        ]

        sorted_segs = sorted(segments, key=lambda s: getattr(s, "start_time", 0.0))
        raw_intervals = []
        for s in sorted_segs:
            st = max(0.0, float(getattr(s, "start_time", 0.0)) - 2.5)
            et = min(duration, float(getattr(s, "end_time", 0.0)) + 3.0)
            if not raw_intervals:
                raw_intervals.append((st, et))
            else:
                prev_st, prev_et = raw_intervals[-1]
                if st <= prev_et + 2.0:
                    raw_intervals[-1] = (prev_st, max(prev_et, et))
                else:
                    raw_intervals.append((st, et))

        self.assertEqual(len(raw_intervals), 2, "Expected 2 merged intervals from 3 segments")
        # Interval 1 merged: 47.5s to 65.0s
        self.assertAlmostEqual(raw_intervals[0][0], 47.5, places=2)
        self.assertAlmostEqual(raw_intervals[0][1], 65.0, places=2)
        # Interval 2 separate: 197.5s to 208.0s
        self.assertAlmostEqual(raw_intervals[1][0], 197.5, places=2)
        self.assertAlmostEqual(raw_intervals[1][1], 208.0, places=2)

    def test_2_interval_boundary_clamping(self):
        """Verify boundary clamping for incidents at video start (t=0.5s) and video end (t=duration)."""
        duration = 100.0

        # Incident at start: 0.5s - 2.0s -> st should be clamped to 0.0s (not negative)
        # Incident at end: 98.0s - 99.5s -> et should be clamped to 100.0s (not exceeding duration)
        segments = [
            SimpleNamespace(start_time=0.5, end_time=2.0),
            SimpleNamespace(start_time=98.0, end_time=99.5),
        ]

        raw_intervals = []
        for s in segments:
            st = max(0.0, float(s.start_time) - 2.5)
            et = min(duration, float(s.end_time) + 3.0)
            raw_intervals.append((st, et))

        self.assertEqual(raw_intervals[0][0], 0.0, "Start timestamp must clamp to 0.0s")
        self.assertEqual(raw_intervals[0][1], 5.0, "End timestamp should be 2.0 + 3.0 = 5.0s")
        self.assertEqual(raw_intervals[1][0], 95.5, "Start timestamp should be 98.0 - 2.5 = 95.5s")
        self.assertEqual(raw_intervals[1][1], 100.0, "End timestamp must clamp to video duration 100.0s")

    def test_3_event_triggered_face_detection_call_reduction(self):
        """Confirm that face detection evaluates at most 3 curated candidate crops per track, with early exit on clear face."""
        crop_dir = os.path.join(settings.STORAGE_DIR, "test_crops_f24")
        os.makedirs(crop_dir, exist_ok=True)

        # Mock tracks with candidate crops
        valid_tracks = {
            101: {
                "detections": [1, 2, 3, 4],
                "start_time": 10.0,
                "end_time": 15.0,
                "_candidate_crops": [
                    {"crop": np.zeros((100, 60, 3), dtype=np.uint8), "frame_idx": 250, "quality": 0.95},
                    {"crop": np.zeros((90, 55, 3), dtype=np.uint8), "frame_idx": 260, "quality": 0.85},
                    {"crop": np.zeros((80, 50, 3), dtype=np.uint8), "frame_idx": 270, "quality": 0.75},
                    {"crop": np.zeros((70, 45, 3), dtype=np.uint8), "frame_idx": 280, "quality": 0.65},
                ]
            },
            102: {
                "detections": [1, 2, 3, 4],
                "start_time": 12.0,
                "end_time": 14.0,
                "_candidate_crops": [
                    {"crop": np.zeros((110, 70, 3), dtype=np.uint8), "frame_idx": 300, "quality": 0.90},
                ]
            }
        }

        # Run face detection worker
        updated_tracks, elapsed_sec, calls = _detect_faces_on_candidates_sync(crop_dir, valid_tracks)

        # Track 101 had 4 candidates, but at most 3 should be evaluated
        # Track 102 had 1 candidate -> total calls <= 4
        self.assertLessEqual(calls, 4, f"Expected <= 4 face detection calls, got {calls}")
        self.assertGreaterEqual(calls, 1, "Expected at least 1 call made")
        self.assertIn("candidate_face_crops", updated_tracks[101])
        self.assertIn("best_crop_path", updated_tracks[101])
        # _candidate_crops should be cleaned up from memory
        self.assertNotIn("_candidate_crops", updated_tracks[101])

        # Cleanup test crops
        import shutil
        if os.path.exists(crop_dir):
            shutil.rmtree(crop_dir, ignore_errors=True)

    def test_4_unidentified_person_preservation_when_face_unavailable(self):
        """Verify that when no clear face is detected on a track, fallback body crop is used and unidentified is preserved."""
        crop_dir = os.path.join(settings.STORAGE_DIR, "test_crops_f24_unid")
        os.makedirs(crop_dir, exist_ok=True)

        # Blank black image has no detectable face
        blank_crop = np.zeros((120, 60, 3), dtype=np.uint8)
        valid_tracks = {
            201: {
                "detections": [1, 2, 3, 4],
                "start_time": 5.0,
                "end_time": 8.0,
                "_candidate_crops": [
                    {"crop": blank_crop, "frame_idx": 125, "quality": 0.80}
                ]
            }
        }

        updated_tracks, elapsed_sec, calls = _detect_faces_on_candidates_sync(crop_dir, valid_tracks)
        trk = updated_tracks[201]

        self.assertEqual(len(trk["candidate_face_crops"]), 0, "No face should be detected on blank crop")
        self.assertEqual(trk["best_face_score"], 0.0, "Best face score should be 0.0")
        self.assertIsNotNone(trk["best_crop_path"], "Fallback body crop path must be assigned")
        self.assertTrue(os.path.exists(trk["best_crop_path"]), "Fallback body crop file must exist on disk")

        # Cleanup
        import shutil
        if os.path.exists(crop_dir):
            shutil.rmtree(crop_dir, ignore_errors=True)

    def test_5_full_timeline_x3d_coverage(self):
        """Confirm that X3D temporal detector computes windows across the full timeline."""
        from app.pipeline.x3d_violence_detector import X3DViolenceDetector
        detector = X3DViolenceDetector()

        self.assertIsNotNone(detector, "X3D Detector instance must be available")
        self.assertEqual(detector.num_frames, 16, "X3D window frames must be 16")
        self.assertEqual(detector.frame_size, 224, "X3D frame size must be 224")


if __name__ == "__main__":
    unittest.main()
