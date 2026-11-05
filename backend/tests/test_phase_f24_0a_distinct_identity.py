"""
Phase F24.0A: Regression Test Suite for Distinct-Identity Ambiguity Calculation.

Validates:
A. Multi-photo ambiguity check:
   Student A scores 0.82, 0.80, and 0.79 across three photos; Student B scores 0.78.
   The winner must be Student A, runner-up Student B, margin 0.04 -> Rejected as ambiguous (< 0.05).
B. Multi-photo clear match:
   Student A scores 0.82 and 0.80; Student B scores 0.70.
   The winner must be Student A, runner-up Student B, margin 0.12 -> Passes margin gate.
C. Self-competition prevention:
   The two highest-scoring photos belong to Student A.
   Verifies they can never be treated as two competing identities.
D. Sub-threshold rejection:
   Top score below 0.60 -> No identity is accepted.
E. Tied / near-tied different identities:
   Tied or near-tied different identities -> Conservative rejection.
F. Defensive error handling:
   Empty galleries, malformed IDs, non-finite similarities (NaN, Inf) handled safely.
G. End-to-end acceptance gate validation:
   Ensures no identity is accepted when similarity or ambiguity requirements fail.
"""

import sys
import unittest
import uuid
import numpy as np
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))
tests_dir = Path(__file__).resolve().parent
if str(tests_dir) not in sys.path:
    sys.path.insert(0, str(tests_dir))

from app.api.v1.violence import rank_distinct_student_identities
from app.core.config import settings
from run_f23_9e_evaluation import match_face_against_gallery


class TestPhaseF24_0ADistinctIdentityAmbiguity(unittest.TestCase):

    def setUp(self):
        self.sid_a = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        self.sid_b = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
        self.sid_c = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

    def test_a_multi_photo_ambiguity_rejection(self):
        """
        Test A: Student A scores 0.82, 0.80, 0.79 across 3 photos; Student B scores 0.78.
        Winner: A (0.82), Runner-up: B (0.78), Margin: 0.04.
        Must be rejected as ambiguous under the 0.05 rule.
        """
        db_sids = [self.sid_a, self.sid_a, self.sid_a, self.sid_b]
        sims = np.array([0.82, 0.80, 0.79, 0.78], dtype=np.float32)

        best_sid, sim, second_sid, second_sim, margin = rank_distinct_student_identities(db_sids, sims)

        self.assertEqual(best_sid, self.sid_a)
        self.assertAlmostEqual(sim, 0.82, places=4)
        self.assertEqual(second_sid, self.sid_b)
        self.assertAlmostEqual(second_sim, 0.78, places=4)
        self.assertAlmostEqual(margin, 0.04, places=4)

        # Ambiguity gate evaluation
        is_ambiguous = (
            second_sid is not None
            and str(second_sid) != str(best_sid)
            and second_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD
            and (sim - second_sim) < 0.05
        )
        self.assertTrue(is_ambiguous, "Margin 0.04 must be rejected as ambiguous (< 0.05 margin requirement)")

    def test_b_multi_photo_clear_match(self):
        """
        Test B: Student A scores 0.82 and 0.80; Student B scores 0.70.
        Winner: A (0.82), Runner-up: B (0.70), Margin: 0.12.
        Must pass margin gate and qualify for acceptance.
        """
        db_sids = [self.sid_a, self.sid_a, self.sid_b]
        sims = np.array([0.82, 0.80, 0.70], dtype=np.float32)

        best_sid, sim, second_sid, second_sim, margin = rank_distinct_student_identities(db_sids, sims)

        self.assertEqual(best_sid, self.sid_a)
        self.assertAlmostEqual(sim, 0.82, places=4)
        self.assertEqual(second_sid, self.sid_b)
        self.assertAlmostEqual(second_sim, 0.70, places=4)
        self.assertAlmostEqual(margin, 0.12, places=4)

        # Ambiguity gate evaluation
        is_ambiguous = (
            second_sid is not None
            and str(second_sid) != str(best_sid)
            and second_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD
            and (sim - second_sim) < 0.05
        )
        self.assertFalse(is_ambiguous, "Margin 0.12 must pass the ambiguity margin gate")
        self.assertGreaterEqual(sim, settings.RECOGNITION_MEDIUM_THRESHOLD)
        self.assertGreaterEqual(sim, settings.RECOGNITION_HIGH_THRESHOLD)

    def test_c_photos_of_same_student_never_compete_against_themselves(self):
        """
        Test C: The two highest-scoring photos belong to Student A (0.85, 0.81).
        Student B is at 0.65.
        Verifies that photo 2 of Student A is NEVER treated as the competing identity.
        Runner-up MUST be Student B (0.65), NOT Student A photo 2.
        """
        db_sids = [self.sid_a, self.sid_a, self.sid_b]
        sims = np.array([0.85, 0.81, 0.65], dtype=np.float32)

        best_sid, sim, second_sid, second_sim, margin = rank_distinct_student_identities(db_sids, sims)

        self.assertEqual(best_sid, self.sid_a)
        self.assertAlmostEqual(sim, 0.85, places=4)
        # Runner-up must be Student B, NOT Student A photo 2
        self.assertEqual(second_sid, self.sid_b)
        self.assertAlmostEqual(second_sim, 0.65, places=4)
        self.assertAlmostEqual(margin, 0.20, places=4)

        # Test single enrolled student with 3 photos (no competing identities at all)
        single_sids = [self.sid_a, self.sid_a, self.sid_a]
        single_sims = np.array([0.85, 0.81, 0.79], dtype=np.float32)
        b_sid, b_sim, s_sid, s_sim, s_margin = rank_distinct_student_identities(single_sids, single_sims)
        self.assertEqual(b_sid, self.sid_a)
        self.assertAlmostEqual(b_sim, 0.85, places=4)
        self.assertIsNone(s_sid, "No competing identity must yield second_sid = None")
        self.assertAlmostEqual(s_sim, 0.0, places=4)
        self.assertAlmostEqual(s_margin, 0.85, places=4)

    def test_d_sub_threshold_scores_never_accepted(self):
        """
        Test D: Top score below RECOGNITION_MEDIUM_THRESHOLD (0.60).
        Ensure no identity is accepted.
        """
        db_sids = [self.sid_a, self.sid_b]
        sims = np.array([0.58, 0.45], dtype=np.float32)

        best_sid, sim, second_sid, second_sim, margin = rank_distinct_student_identities(db_sids, sims)

        self.assertEqual(best_sid, self.sid_a)
        self.assertAlmostEqual(sim, 0.58, places=4)
        self.assertLess(sim, settings.RECOGNITION_MEDIUM_THRESHOLD)

        # Acceptance check
        is_accepted = best_sid is not None and sim >= settings.RECOGNITION_MEDIUM_THRESHOLD
        self.assertFalse(is_accepted, "Score 0.58 below 0.60 threshold must never be accepted")

    def test_e_tied_or_near_tied_identities_conservatively_rejected(self):
        """
        Test E: Tied (0.80 vs 0.80) or near-tied (0.76 vs 0.75, margin 0.01) different identities.
        Must be conservatively rejected as ambiguous.
        """
        # Exact tie between distinct identities
        db_sids = [self.sid_a, self.sid_b]
        sims_tie = np.array([0.80, 0.80], dtype=np.float32)
        best_sid, sim, second_sid, second_sim, margin = rank_distinct_student_identities(db_sids, sims_tie)
        self.assertAlmostEqual(margin, 0.0, places=4)
        is_ambiguous_tie = (
            second_sid is not None
            and str(second_sid) != str(best_sid)
            and second_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD
            and (sim - second_sim) < 0.05
        )
        self.assertTrue(is_ambiguous_tie, "Exact tie must be rejected as ambiguous")

        # Near tie: margin = 0.01
        sims_near = np.array([0.76, 0.75], dtype=np.float32)
        best_sid, sim, second_sid, second_sim, margin = rank_distinct_student_identities(db_sids, sims_near)
        self.assertAlmostEqual(margin, 0.01, places=4)
        is_ambiguous_near = (
            second_sid is not None
            and str(second_sid) != str(best_sid)
            and second_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD
            and (sim - second_sim) < 0.05
        )
        self.assertTrue(is_ambiguous_near, "Near tie (margin 0.01) must be rejected as ambiguous")

    def test_f_defensive_error_handling(self):
        """
        Test F: Empty galleries, None/malformed IDs, non-finite values (NaN, Inf).
        Must be handled safely according to project conventions.
        """
        # 1. Empty input
        res_empty = rank_distinct_student_identities([], np.array([]))
        self.assertEqual(res_empty, (None, 0.0, None, 0.0, 0.0))

        res_none = rank_distinct_student_identities(None, None)
        self.assertEqual(res_none, (None, 0.0, None, 0.0, 0.0))

        # 2. Non-finite values (NaN, Inf)
        sids = [self.sid_a, self.sid_b, self.sid_c]
        sims_nan = np.array([np.nan, 0.77, np.inf], dtype=np.float32)
        best_sid, sim, second_sid, second_sim, margin = rank_distinct_student_identities(sids, sims_nan)
        self.assertEqual(best_sid, self.sid_b)
        self.assertAlmostEqual(sim, 0.77, places=4)
        self.assertIsNone(second_sid)
        self.assertAlmostEqual(second_sim, 0.0, places=4)

        # 3. None student ID in list
        sids_with_none = [None, self.sid_a]
        sims_valid = np.array([0.90, 0.75], dtype=np.float32)
        best_sid, sim, second_sid, second_sim, margin = rank_distinct_student_identities(sids_with_none, sims_valid)
        self.assertEqual(best_sid, self.sid_a)
        self.assertAlmostEqual(sim, 0.75, places=4)
        self.assertIsNone(second_sid)

        # 4. Mixed string and UUID identity normalization
        str_a = str(self.sid_a)
        mixed_sids = [self.sid_a, str_a, self.sid_b]
        mixed_sims = np.array([0.80, 0.85, 0.70], dtype=np.float32)
        b_sid, b_sim, s_sid, s_sim, m = rank_distinct_student_identities(mixed_sids, mixed_sims)
        self.assertIn(str(b_sid), [str(self.sid_a)])
        self.assertAlmostEqual(b_sim, 0.85, places=4)
        self.assertEqual(s_sid, self.sid_b)
        self.assertAlmostEqual(s_sim, 0.70, places=4)
        self.assertAlmostEqual(m, 0.15, places=4)

    def test_g_evaluation_harness_distinct_identity_parity(self):
        """
        Test G: Verify match_face_against_gallery in evaluation harness implements
        exact distinct-identity parity.
        """
        # Gallery with Student A (2 photos) and Student B (1 photo)
        # Dummy 512-d normalized basis vectors
        v_a = np.zeros(512, dtype=np.float32)
        v_a[0] = 1.0

        v_b = np.zeros(512, dtype=np.float32)
        v_b[1] = 1.0

        # Gallery matrix: row 0 = A (photo 1), row 1 = A (photo 2), row 2 = B (photo 1)
        matrix = np.vstack([v_a, v_a, v_b])
        gallery = {
            "matrix": matrix,
            "sids": [str(self.sid_a), str(self.sid_a), str(self.sid_b)],
            "names": ["Student Alpha", "Student Alpha", "Student Beta"],
            "rolls": ["R001", "R001", "R002"],
            "count": 3
        }

        # Probe matching Student A strongly (photo 1: 0.82, photo 2: 0.80) and B weakly (0.65)
        # Synthesize probe vector giving dot products: [0.82, 0.82, 0.65]
        # In match_face_against_gallery:
        # Student Alpha must win, Runner-up must be Student Beta, NOT Student Alpha
        probe = np.zeros(512, dtype=np.float32)
        probe[0] = 0.82
        probe[1] = 0.65
        probe[2] = np.sqrt(max(0.0, 1.0 - (0.82**2 + 0.65**2)))
        probe = probe / np.linalg.norm(probe)

        top_name, top_sim, sec_name, sec_sim, margin, is_confirmed = match_face_against_gallery(probe, gallery)

        self.assertEqual(top_name, "Student Alpha")
        self.assertEqual(sec_name, "Student Beta")
        self.assertNotEqual(sec_name, "Student Alpha", "Self-photo can never be runner-up in evaluation harness")
        self.assertTrue(is_confirmed, "Clear match (margin >= 0.05) must be confirmed")


if __name__ == "__main__":
    unittest.main()
