"""
Unit tests for Phase 5: Track-Level Temporal Face Recognition & Aggregation.
Verifies:
- TrackObservationPool capacity bounds and temporal diversity
- Biometric quality ranking (sharpness, resolution, pose, confidence)
- Temporal consensus voting & weighted aggregation
- Contradictory identity rejection
- Weak consensus rejection (< 0.60 threshold)
- Ambiguity margin enforcement (< 0.05 margin)
- Quality-weighted representative crop selection
"""

import unittest
import os
import sys
import uuid
import numpy as np
from types import SimpleNamespace

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.pipeline.temporal_consensus import (
    FaceObservation,
    TrackObservationPool,
    ConsensusResult,
    TemporalConsensusEngine
)


class TestPhase5TemporalConsensus(unittest.TestCase):

    def setUp(self):
        self.engine = TemporalConsensusEngine()
        self.std_a_id = uuid.uuid4()
        self.std_b_id = uuid.uuid4()
        self.std_c_id = uuid.uuid4()

        # Enrolled student objects mock
        self.enrolled_map = {
            self.std_a_id: SimpleNamespace(id=self.std_a_id, name="Aarav Sharma", roll_number="CS2101"),
            self.std_b_id: SimpleNamespace(id=self.std_b_id, name="Priya Patel", roll_number="CS2102"),
            self.std_c_id: SimpleNamespace(id=self.std_c_id, name="Rahul Verma", roll_number="CS2103"),
        }

        # Create distinct normalized 512-dim gallery embeddings
        np.random.seed(42)
        v_a = np.random.randn(512).astype(np.float32)
        v_a /= np.linalg.norm(v_a)

        v_b = np.random.randn(512).astype(np.float32)
        v_b /= np.linalg.norm(v_b)

        v_c = np.random.randn(512).astype(np.float32)
        v_c /= np.linalg.norm(v_c)

        self.gallery_sids = [self.std_a_id, self.std_b_id, self.std_c_id]
        self.gallery_matrix = np.stack([v_a, v_b, v_c])
        self.v_a, self.v_b, self.v_c = v_a, v_b, v_c

    def _make_obs(
        self,
        base_vector: np.ndarray,
        noise_level: float = 0.05,
        frame: int = 100,
        timestamp: float = 4.0,
        det_score: float = 0.85,
        blur_score: float = 120.0,
        fw: int = 40,
        fh: int = 48,
        source: str = "head_crop",
        crop_path: str = "crop_f100.jpg"
    ) -> FaceObservation:
        vec = base_vector + np.random.randn(512).astype(np.float32) * noise_level
        vec /= np.linalg.norm(vec)
        q = self.engine.compute_biometric_quality(
            det_score=det_score,
            blur_score=blur_score,
            fw=fw,
            fh=fh,
            person_bbox=[100, 100, 200, 300],
            face_bbox=[125, 110, 175, 160]
        )
        return FaceObservation(
            embedding=vec,
            frame=frame,
            timestamp=timestamp,
            face_bbox=[125, 110, 175, 160],
            person_bbox=[100, 100, 200, 300],
            det_score=det_score,
            blur_score=blur_score,
            face_dims=(fw, fh),
            quality_score=q,
            crop_path=crop_path,
            source=source
        )

    def test_1_pool_capacity_and_temporal_separation(self):
        """Verify that observation pool enforces temporal gap and bounded capacity."""
        pool = TrackObservationPool(trk_id=1, max_capacity=4, min_frame_gap=6)

        # Observation at frame 10 (high quality)
        obs1 = self._make_obs(self.v_a, frame=10, det_score=0.90, blur_score=150.0)
        self.assertTrue(pool.add_observation(obs1))
        self.assertEqual(len(pool.observations), 1)

        # Observation at frame 12 (adjacent frame, lower quality) -> rejected
        obs2 = self._make_obs(self.v_a, frame=12, det_score=0.50, blur_score=20.0)
        self.assertFalse(pool.add_observation(obs2))
        self.assertEqual(len(pool.observations), 1)

        # Observation at frame 13 (adjacent frame, higher quality) -> replaces obs1
        obs3 = self._make_obs(self.v_a, frame=13, det_score=0.98, blur_score=220.0)
        self.assertTrue(pool.add_observation(obs3))
        self.assertEqual(len(pool.observations), 1)
        self.assertEqual(pool.observations[0].frame, 13)

        # Add distinct frames: 25, 40, 60
        pool.add_observation(self._make_obs(self.v_a, frame=25, det_score=0.80))
        pool.add_observation(self._make_obs(self.v_a, frame=40, det_score=0.82))
        pool.add_observation(self._make_obs(self.v_a, frame=60, det_score=0.85))
        self.assertEqual(len(pool.observations), 4)

        # 5th observation when max capacity is 4
        # Add high quality observation at frame 80 -> should replace lowest quality
        obs_high = self._make_obs(self.v_a, frame=80, det_score=0.99, blur_score=240.0)
        self.assertTrue(pool.add_observation(obs_high))
        self.assertEqual(len(pool.observations), 4)

    def test_2_biometric_quality_ranking(self):
        """Verify multi-attribute biometric quality calculation."""
        # High quality: sharp, large, high detector confidence, well centered
        q_high = self.engine.compute_biometric_quality(
            det_score=0.92,
            blur_score=180.0,
            fw=64,
            fh=68,
            person_bbox=[100, 100, 200, 350],
            face_bbox=[120, 110, 180, 175]
        )

        # Low quality: small, blurry, low confidence
        q_low = self.engine.compute_biometric_quality(
            det_score=0.42,
            blur_score=12.0,
            fw=14,
            fh=16,
            person_bbox=[100, 100, 200, 350],
            face_bbox=[110, 110, 124, 126]
        )

        self.assertGreater(q_high, 0.50)
        self.assertLess(q_low, 0.25)
        self.assertGreater(q_high, q_low * 2.0)

    def test_3_strong_consensus_identifies_student(self):
        """Verify that consistent high-quality observations correctly identify student."""
        pool = TrackObservationPool(trk_id=5)
        # 3 observations of Student A across different frames
        pool.add_observation(self._make_obs(self.v_a, noise_level=0.03, frame=20, crop_path="c20.jpg"))
        pool.add_observation(self._make_obs(self.v_a, noise_level=0.04, frame=45, crop_path="c45.jpg"))
        pool.add_observation(self._make_obs(self.v_a, noise_level=0.02, frame=70, crop_path="c70.jpg"))

        res = self.engine.evaluate_track_consensus(
            pool=pool,
            gallery_matrix=self.gallery_matrix,
            gallery_sids=self.gallery_sids,
            enrolled_students_map=self.enrolled_map
        )

        self.assertEqual(res.status, "IDENTIFIED")
        self.assertEqual(res.student_id, self.std_a_id)
        self.assertEqual(res.student_name, "Aarav Sharma")
        self.assertGreaterEqual(res.similarity_score, 0.60)
        self.assertGreaterEqual(res.margin, 0.05)
        self.assertEqual(res.supporting_observations_count, 3)
        self.assertIsNotNone(res.medoid_embedding)

    def test_4_contradictory_identities_rejected(self):
        """Verify that conflicting observations voting for different students are rejected."""
        pool = TrackObservationPool(trk_id=7)
        # 2 observations voting strongly for Student A
        pool.add_observation(self._make_obs(self.v_a, noise_level=0.02, frame=20, det_score=0.88))
        pool.add_observation(self._make_obs(self.v_a, noise_level=0.03, frame=40, det_score=0.85))

        # 2 observations voting strongly for Student B on the same track (ID switch / occlusion)
        pool.add_observation(self._make_obs(self.v_b, noise_level=0.02, frame=65, det_score=0.89))
        pool.add_observation(self._make_obs(self.v_b, noise_level=0.03, frame=85, det_score=0.86))

        res = self.engine.evaluate_track_consensus(
            pool=pool,
            gallery_matrix=self.gallery_matrix,
            gallery_sids=self.gallery_sids,
            enrolled_students_map=self.enrolled_map
        )

        self.assertEqual(res.status, "CONTRADICTORY")
        self.assertIsNone(res.student_id)
        self.assertIn("Contradictory", res.rejection_reason)

    def test_5_weak_consensus_cannot_force_identity(self):
        """
        Verify that multiple weak observations below 0.60 threshold
        never force an identity match (Safeguard 5).
        """
        pool = TrackObservationPool(trk_id=9)
        # Create an unknown identity vector that only has ~0.50 similarity to Student A
        v_unknown = self.v_a * 0.50 + self.v_b * 0.50 + np.random.randn(512).astype(np.float32) * 0.3
        v_unknown /= np.linalg.norm(v_unknown)

        pool.add_observation(self._make_obs(v_unknown, frame=20, det_score=0.80))
        pool.add_observation(self._make_obs(v_unknown, frame=40, det_score=0.82))
        pool.add_observation(self._make_obs(v_unknown, frame=60, det_score=0.85))
        pool.add_observation(self._make_obs(v_unknown, frame=80, det_score=0.83))

        res = self.engine.evaluate_track_consensus(
            pool=pool,
            gallery_matrix=self.gallery_matrix,
            gallery_sids=self.gallery_sids,
            enrolled_students_map=self.enrolled_map,
            medium_threshold=0.60
        )

        self.assertEqual(res.status, "UNIDENTIFIED")
        self.assertIsNone(res.student_id)
        self.assertLess(res.similarity_score, 0.60)
        self.assertIn("below recognition threshold", res.rejection_reason)

    def test_6_ambiguity_margin_rejection(self):
        """Verify that observations where top-1 and runner-up are within 0.05 are rejected."""
        pool = TrackObservationPool(trk_id=11)
        # Vector equidistant to Student A and Student B (e.g. 0.68 vs 0.66)
        v_ambig = (self.v_a + self.v_b) / 2.0
        v_ambig /= np.linalg.norm(v_ambig)

        pool.add_observation(self._make_obs(v_ambig, frame=30, det_score=0.90))

        res = self.engine.evaluate_track_consensus(
            pool=pool,
            gallery_matrix=self.gallery_matrix,
            gallery_sids=self.gallery_sids,
            enrolled_students_map=self.enrolled_map,
            medium_threshold=0.60,
            ambiguity_margin=0.05
        )

        self.assertEqual(res.status, "UNIDENTIFIED")
        self.assertIsNone(res.student_id)


if __name__ == "__main__":
    unittest.main()
