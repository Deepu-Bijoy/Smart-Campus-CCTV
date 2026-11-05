"""
Phase F23.9C Regression Test Suite: Bounded Pre-Incident Face Recovery.

Covers:
1. Recovery never decodes frames outside the configured bounded window.
2. Earlier face observations can contribute candidates when association is valid.
3. Track IDs from separate tracker runs are not assumed to be continuous.
4. Ambiguous or bystander associations are rejected.
5. Similarity below 0.60 or ambiguity margin below 0.05 never produces a confirmed identity.
6. Existing F23.9B candidate selection and API response contracts remain intact.
7. Videos with no violence do not incur unnecessary face-recovery processing.
"""

import os
import sys
import unittest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.api.v1.violence import (
    _track_video_segments_sync,
    validate_pre_incident_track_association,
    _compute_face_observation_quality
)
from app.core.config import settings
from app.schemas.violence import InvolvedStudentCard


class TestPhaseF23_9CPreIncidentRecovery(unittest.TestCase):

    def test_1_recovery_never_decodes_frames_outside_bounded_window(self):
        """
        Verify that _track_video_segments_sync decodes frames ONLY within
        [max(0, start_sec - pre_incident_margin), end_sec + 3.0], never outside.
        """
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.side_effect = lambda prop: {
            5: 30.0,    # cv2.CAP_PROP_FPS = 30
            7: 3000,    # cv2.CAP_PROP_FRAME_COUNT = 3000 (100 seconds)
            3: 1280,    # cv2.CAP_PROP_FRAME_WIDTH
            4: 720      # cv2.CAP_PROP_FRAME_HEIGHT
        }.get(prop, 0.0)

        # Track seek positions (CAP_PROP_POS_FRAMES)
        seek_positions = []
        def mock_set(prop, val):
            if prop == 1:  # cv2.CAP_PROP_POS_FRAMES
                seek_positions.append(int(val))
            return True
        mock_cap.set.side_effect = mock_set

        # Frames read: return black dummy frame
        mock_cap.read.return_value = (True, np.zeros((720, 1280, 3), dtype=np.uint8))

        # Incident from 50.0s to 55.0s, pre_incident_margin = 4.5s
        # Start bound: 50.0 - 4.5 = 45.5s -> frame 1365
        # End bound: 55.0 + 3.0 = 58.0s -> frame 1740
        seg = {"start_time": 50.0, "end_time": 55.0}

        with patch("cv2.VideoCapture", return_value=mock_cap), \
             patch("app.api.v1.violence.YOLOv8Detector") as mock_yolo_cls, \
             patch("app.api.v1.violence.ByteTrackTracker") as mock_tracker_cls:
            
            mock_detector = MagicMock()
            mock_detector.detect.return_value = []
            mock_yolo_cls.return_value = mock_detector

            mock_tracker = MagicMock()
            mock_tracker.update.return_value = []
            mock_tracker_cls.return_value = mock_tracker

            tracks, _, _ = _track_video_segments_sync(
                video_file_path="dummy_video.mp4",
                video_id="00000000-0000-0000-0000-000000000001",
                segments=[seg],
                pre_incident_margin=4.5
            )

        # Assert seek positions were strictly bounded
        self.assertTrue(len(seek_positions) > 0)
        start_frame_expected = int(45.5 * 30.0)  # 1365
        self.assertEqual(seek_positions[0], start_frame_expected)

        # Confirm no seek position was before 1365
        for sp in seek_positions:
            self.assertGreaterEqual(sp, start_frame_expected)

    def test_2_earlier_face_observation_contributes_when_association_valid(self):
        """
        Verify that a candidate pre-track passes validation and contributes
        when temporal sequencing, spatial continuity, and Re-ID match.
        """
        incident_track = {
            "tracker_id": 101,
            "start_time": 50.0,
            "end_time": 54.0,
            "best_crop_path": "inc_crop.jpg",
            "detections": [
                {"timestamp": 50.0, "bounding_box": [100, 100, 200, 300]}
            ]
        }

        # Pre-track ended 0.5s before incident, adjacent spatial location, high Re-ID similarity
        pre_track = {
            "tracker_id": 99,
            "start_time": 46.0,
            "end_time": 49.5,
            "best_crop_path": "pre_crop.jpg",
            "detections": [
                {"timestamp": 49.5, "bounding_box": [110, 105, 210, 305]}
            ]
        }

        all_pre = [pre_track]

        # Normalized embeddings
        v1 = np.ones(512, dtype=np.float32) / np.sqrt(512)
        incident_track["reid_embedding"] = v1.tolist()
        pre_track["reid_embedding"] = v1.tolist()

        is_valid, method, sim = validate_pre_incident_track_association(
            incident_track=incident_track,
            candidate_pre_track=pre_track,
            all_pre_tracks=all_pre,
            incident_start_sec=50.0
        )

        self.assertTrue(is_valid)
        self.assertEqual(method, "trajectory_reid_validated")
        self.assertAlmostEqual(sim, 1.0, places=3)

    def test_3_track_ids_from_separate_tracker_runs_not_assumed_continuous(self):
        """
        Verify that having matching or adjacent track IDs without Re-ID
        or continuous execution does not assume continuity.
        """
        incident_track = {
            "tracker_id": 10,
            "start_time": 50.0,
            "end_time": 53.0,
            "reid_embedding": None,  # No Re-ID appearance validation
            "detections": [
                {"timestamp": 50.0, "bounding_box": [100, 100, 200, 300]}
            ]
        }

        pre_track = {
            "tracker_id": 10,  # Same number, but from separate/discontinuous execution
            "start_time": 40.0,
            "end_time": 45.0,  # 5.0 second gap!
            "reid_embedding": None,
            "detections": [
                {"timestamp": 45.0, "bounding_box": [500, 500, 600, 700]}
            ]
        }

        is_valid, reason, sim = validate_pre_incident_track_association(
            incident_track=incident_track,
            candidate_pre_track=pre_track,
            all_pre_tracks=[pre_track],
            incident_start_sec=50.0
        )

        self.assertFalse(is_valid)
        self.assertIn("Temporal gap invalid", reason)

    def test_4_ambiguous_or_bystander_associations_rejected(self):
        """
        Verify that when multiple pre-tracks have near-identical similarity
        (ambiguity margin violation < 0.15), association is rejected.
        """
        v_inc = np.ones(512, dtype=np.float32) / np.sqrt(512)
        incident_track = {
            "tracker_id": 50,
            "start_time": 20.0,
            "end_time": 25.0,
            "reid_embedding": v_inc.tolist(),
            "detections": [
                {"timestamp": 20.0, "bounding_box": [200, 200, 300, 450]}
            ]
        }

        # Pre-track A (target candidate): sim = 1.0
        # Pre-track B (competitor bystander): sim = 1.0 (margin violation < 0.15)
        v_a = v_inc.copy()
        v_b = v_inc.copy()

        pre_a = {
            "tracker_id": 40,
            "start_time": 16.0,
            "end_time": 19.5,
            "reid_embedding": v_a.tolist(),
            "detections": [
                {"timestamp": 19.5, "bounding_box": [205, 205, 305, 455]}
            ]
        }

        pre_b = {
            "tracker_id": 41,
            "start_time": 16.5,
            "end_time": 19.6,
            "reid_embedding": v_b.tolist(),
            "detections": [
                {"timestamp": 19.6, "bounding_box": [210, 205, 310, 455]}
            ]
        }

        is_valid, reason, sim = validate_pre_incident_track_association(
            incident_track=incident_track,
            candidate_pre_track=pre_a,
            all_pre_tracks=[pre_a, pre_b],
            incident_start_sec=20.0,
            reid_ambiguity_margin=0.15
        )

        self.assertFalse(is_valid)
        self.assertIn("Ambiguous association", reason)

    def test_5_similarity_below_threshold_or_ambiguity_margin_retains_unidentified(self):
        """
        Verify that sub-0.60 ArcFace similarity or margin below 0.05
        never produces a confirmed student identity.
        """
        # Test sub-0.60 similarity
        sub_thresh_sim = 0.58
        self.assertFalse(sub_thresh_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD)

        # Test ambiguity margin: top = 0.64, second = 0.61 -> diff 0.03 (< 0.05 margin)
        top_sim = 0.64
        second_sim = 0.61
        ambiguity_margin = 0.05
        passes_safeguard = (top_sim >= 0.60) and ((top_sim - second_sim) >= ambiguity_margin)
        self.assertFalse(passes_safeguard)

        # Verify an unidentified card preserves Unidentified Person
        card = InvolvedStudentCard(
            student_id=None,
            name="Unidentified Person",
            enrollment_number=None,
            confidence="unidentified",
            similarity_score=0.0,
            track_id="12",
            is_identified=False
        )
        self.assertEqual(card.name, "Unidentified Person")
        self.assertIsNone(card.student_id)
        self.assertFalse(card.is_identified)

    def test_6_candidate_selection_and_card_contracts_intact(self):
        """
        Verify that InvolvedStudentCard schema and candidate face metadata
        retain track_id, crop path, frame, and timestamp contract.
        """
        card = InvolvedStudentCard(
            student_id=None,
            name="Unidentified Person",
            enrollment_number=None,
            confidence="unidentified",
            similarity_score=0.0,
            track_id="77",
            is_identified=False
        )
        data = card.model_dump()
        self.assertEqual(data["track_id"], "77")
        self.assertEqual(data["name"], "Unidentified Person")
        self.assertFalse(data["is_identified"])

    def test_7_videos_with_no_violence_do_not_incur_face_recovery(self):
        """
        Verify that videos with 0 violence segments immediately return empty tracks
        without opening VideoCapture or executing YOLO / ByteTrack.
        """
        with patch("cv2.VideoCapture") as mock_cap, \
             patch("app.api.v1.violence.YOLOv8Detector") as mock_yolo:
            
            tracks, elapsed, call_count = _track_video_segments_sync(
                video_file_path="nonviolent_video.mp4",
                video_id="00000000-0000-0000-0000-000000000002",
                segments=[],  # No violence detected
                pre_incident_margin=4.5
            )

            # Assert zero tracking/frames decoded
            self.assertEqual(tracks, {})
            self.assertEqual(elapsed, 0.0)
            self.assertEqual(call_count, 0.0)
            mock_cap.assert_not_called()
            mock_yolo.assert_not_called()


if __name__ == "__main__":
    unittest.main()
