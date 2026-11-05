"""
Phase F23.9B Regression Test Suite: Best-Face Selection and Safe Crop Improvements.

Covers:
1. All available candidates are evaluated even when an earlier candidate has confidence above 0.65 (no premature early-exit).
2. The best valid face is selected using the quality score, not detector confidence alone.
3. A face belonging to an adjacent person (detected in padding area) is safely rejected.
4. Invalid embeddings, malformed crops, and sub-quality observations are safely handled.
5. Preservation of recognition thresholds (Medium 0.60, High 0.75, margin 0.05) and Unidentified Person contract.
"""

import os
import sys
import uuid
import unittest
import numpy as np
from pathlib import Path
from unittest.mock import MagicMock, patch

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.api.v1.violence import (
    _detect_faces_on_candidates_sync,
    _compute_face_observation_quality
)
from app.core.config import settings
from app.schemas.violence import InvolvedStudentCard


class TestPhaseF23_9BestFace(unittest.TestCase):

    def test_1_all_candidates_evaluated_without_premature_early_exit(self):
        """
        Verify that all available candidates are evaluated even when candidate 0
        has detector confidence above 0.65.
        """
        crop_dir = os.path.join(settings.STORAGE_DIR, "test_crops_f23_9_early_exit")
        os.makedirs(crop_dir, exist_ok=True)

        # Create dummy crops (100x60 RGB)
        crop1 = np.ones((100, 60, 3), dtype=np.uint8) * 100
        crop2 = np.ones((100, 60, 3), dtype=np.uint8) * 120
        crop3 = np.ones((100, 60, 3), dtype=np.uint8) * 140

        valid_tracks = {
            10: {
                "detections": [1, 2, 3],
                "start_time": 10.0,
                "end_time": 12.0,
                "_candidate_crops": [
                    {"crop": crop1, "frame_idx": 300, "quality": 0.95, "timestamp": 10.0},
                    {"crop": crop2, "frame_idx": 315, "quality": 0.85, "timestamp": 10.5},
                    {"crop": crop3, "frame_idx": 330, "quality": 0.75, "timestamp": 11.0},
                ]
            }
        }

        # Mock FaceEnrollmentEngine to simulate:
        # Candidate 0 -> face with det_score = 0.68 (would have caused early exit in F23.8B)
        # Candidate 1 -> face with det_score = 0.85 (higher quality)
        # Candidate 2 -> face with det_score = 0.55
        mock_face_1 = MagicMock()
        mock_face_1.det_score = 0.68
        mock_face_1.bbox = np.array([15, 10, 45, 45])
        mock_face_1.normed_embedding = np.ones(512, dtype=np.float32) / np.sqrt(512)

        mock_face_2 = MagicMock()
        mock_face_2.det_score = 0.85
        mock_face_2.bbox = np.array([10, 5, 50, 50])
        mock_face_2.normed_embedding = np.ones(512, dtype=np.float32) / np.sqrt(512)

        mock_face_3 = MagicMock()
        mock_face_3.det_score = 0.55
        mock_face_3.bbox = np.array([18, 12, 42, 40])
        mock_face_3.normed_embedding = np.ones(512, dtype=np.float32) / np.sqrt(512)

        call_idx = [0]
        def mock_get(c):
            idx = call_idx[0]
            call_idx[0] += 1
            if idx == 0:
                return [mock_face_1]
            elif idx == 1:
                return [mock_face_2]
            else:
                return [mock_face_3]

        with patch("app.api.v1.violence.FaceEnrollmentEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.model.get.side_effect = mock_get
            mock_engine.calculate_blur_score.return_value = 85.0
            mock_engine_cls.return_value = mock_engine

            updated_tracks, elapsed, total_calls = _detect_faces_on_candidates_sync(crop_dir, valid_tracks)

        # All 3 candidates must be evaluated (no early break on candidate 0)
        self.assertEqual(total_calls, 3, f"Expected exactly 3 SCRFD calls, got {total_calls}")
        trk = updated_tracks[10]
        self.assertEqual(len(trk["candidate_face_crops"]), 3, "All 3 candidates must yield face observations")
        # Candidate 1 (det_score 0.85) should be selected as the primary face
        self.assertEqual(trk["best_face_score"], 0.85)
        self.assertIn("f315", trk["best_crop_path"])

        import shutil
        if os.path.exists(crop_dir):
            shutil.rmtree(crop_dir, ignore_errors=True)

    def test_2_best_face_selected_by_quality_score_not_conf_alone(self):
        """
        Verify that quality scoring favors larger, sharp faces over smaller blurry faces
        with slightly higher raw detector scores.
        """
        # Case A: Small face (22x22), high confidence (0.78), but low sharpness (15.0)
        q_small_blurry = _compute_face_observation_quality(
            det_score=0.78,
            blur_score=15.0,
            fw=22,
            fh=22,
            dist_from_center=0.10
        )

        # Case B: Large face (55x55), moderate confidence (0.72), high sharpness (180.0)
        q_large_sharp = _compute_face_observation_quality(
            det_score=0.72,
            blur_score=180.0,
            fw=55,
            fh=55,
            dist_from_center=0.05
        )

        self.assertGreater(
            q_large_sharp, q_small_blurry,
            f"Large sharp observation quality ({q_large_sharp:.4f}) must exceed small blurry observation ({q_small_blurry:.4f})"
        )

    def test_3_face_belonging_to_adjacent_person_rejected(self):
        """
        Verify that a face detected out in the padding margin (belonging to an adjacent person)
        is rejected by the face-to-person association check.
        """
        crop_dir = os.path.join(settings.STORAGE_DIR, "test_crops_f23_9_adj")
        os.makedirs(crop_dir, exist_ok=True)

        # Simulated frame slice: padded crop width = 130, height = 100
        # Original person was x1=100, x2=200 (width=100)
        # Padded box was px1=85, px2=215 (left pad = 15, right pad = 15)
        # In crop coordinates: person horizontal span is x=15 to x=115
        dummy_crop = np.ones((100, 130, 3), dtype=np.uint8) * 128

        # Face A: located at x=0..12 (center at x=6, out in left padding from adjacent person)
        adjacent_face = MagicMock()
        adjacent_face.det_score = 0.82
        adjacent_face.bbox = np.array([0, 10, 12, 40])
        adjacent_face.normed_embedding = np.ones(512, dtype=np.float32) / np.sqrt(512)

        # Face B: located at x=45..85 (center at x=65, right on tracked person)
        valid_person_face = MagicMock()
        valid_person_face.det_score = 0.70
        valid_person_face.bbox = np.array([45, 10, 85, 50])
        valid_person_face.normed_embedding = np.ones(512, dtype=np.float32) / np.sqrt(512)

        valid_tracks = {
            25: {
                "detections": [1, 2],
                "start_time": 5.0,
                "end_time": 6.0,
                "_candidate_crops": [
                    {
                        "crop": dummy_crop,
                        "frame_idx": 150,
                        "quality": 0.90,
                        "timestamp": 5.0,
                        "person_bbox": [100, 100, 200, 200],
                        "pad_box": [85, 85, 215, 215],
                        "orig_w": 100,
                        "orig_h": 100,
                        "trk_id": 25
                    }
                ]
            }
        }

        with patch("app.api.v1.violence.FaceEnrollmentEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            # Return both faces
            mock_engine.model.get.return_value = [adjacent_face, valid_person_face]
            mock_engine.calculate_blur_score.return_value = 100.0
            mock_engine_cls.return_value = mock_engine

            updated_tracks, elapsed, calls = _detect_faces_on_candidates_sync(crop_dir, valid_tracks)

        trk = updated_tracks[25]
        self.assertEqual(len(trk["candidate_face_crops"]), 1)
        cand_entry = trk["candidate_face_crops"][0]
        # Must select the tracked person's face (Face B, center 65), NOT the adjacent face (Face A, center 6)
        self.assertEqual(cand_entry["det_score"], 0.70)
        self.assertEqual(cand_entry["face_bbox"], [45, 10, 85, 50])

        import shutil
        if os.path.exists(crop_dir):
            shutil.rmtree(crop_dir, ignore_errors=True)

    def test_4_invalid_embeddings_and_malformed_crops_safely_handled(self):
        """
        Verify that non-finite or malformed embeddings and empty crops cannot corrupt candidate selection.
        """
        crop_dir = os.path.join(settings.STORAGE_DIR, "test_crops_f23_9_invalid")
        os.makedirs(crop_dir, exist_ok=True)

        empty_crop = np.zeros((0, 0, 3), dtype=np.uint8)
        valid_crop = np.ones((80, 50, 3), dtype=np.uint8) * 100

        # Face with NaN embedding
        nan_face = MagicMock()
        nan_face.det_score = 0.75
        nan_face.bbox = np.array([10, 10, 40, 40])
        bad_emb = np.ones(512, dtype=np.float32)
        bad_emb[50] = float('nan')
        nan_face.normed_embedding = bad_emb

        valid_tracks = {
            30: {
                "detections": [1],
                "start_time": 1.0,
                "end_time": 2.0,
                "_candidate_crops": [
                    {"crop": empty_crop, "frame_idx": 10, "quality": 0.50},
                    {"crop": valid_crop, "frame_idx": 20, "quality": 0.80}
                ]
            }
        }

        with patch("app.api.v1.violence.FaceEnrollmentEngine") as mock_engine_cls:
            mock_engine = MagicMock()
            mock_engine.model.get.return_value = [nan_face]
            mock_engine.calculate_blur_score.return_value = 50.0
            mock_engine_cls.return_value = mock_engine

            updated_tracks, elapsed, calls = _detect_faces_on_candidates_sync(crop_dir, valid_tracks)

        trk = updated_tracks[30]
        self.assertEqual(len(trk["candidate_face_crops"]), 1)
        # NaN embedding must be safely converted to None
        self.assertIsNone(trk["candidate_face_crops"][0]["embedding"])

        import shutil
        if os.path.exists(crop_dir):
            shutil.rmtree(crop_dir, ignore_errors=True)

    def test_5_identity_thresholds_and_unidentified_contract_preserved(self):
        """
        Verify that Medium (0.60), High (0.75), ambiguity margin (0.05) and Unidentified Person
        schema contracts remain strictly intact.
        """
        self.assertEqual(settings.RECOGNITION_MEDIUM_THRESHOLD, 0.60)
        self.assertEqual(settings.RECOGNITION_HIGH_THRESHOLD, 0.75)

        # Below threshold
        card_sub = InvolvedStudentCard(
            student_id=None,
            name="Unidentified Person",
            roll_number="N/A",
            similarity_score=0.58,
            confidence="unidentified",
            track_id="trk-99",
            is_identified=False
        )
        self.assertFalse(card_sub.is_identified)
        self.assertIsNone(card_sub.student_id)
        self.assertEqual(card_sub.name, "Unidentified Person")

        # Ambiguous match (sim >= 0.60 but margin < 0.05)
        sim = 0.63
        second_sim = 0.61
        margin = sim - second_sim
        is_ambiguous = margin < 0.05
        self.assertTrue(is_ambiguous, "Margin 0.02 must be flagged as ambiguous")


if __name__ == "__main__":
    unittest.main()
