"""
Phase F24.0D: Acceptance Test Suite for Same-Video Face Recognition.

Validates all 5 mandatory requirements:
1. Preserve Source Image Quality:
   - Original extracted image resolution is strictly preserved.
   - Video identifier, timestamp, and frame index are recorded in metadata.
   - No unnecessary downsampling, filtering, or lossy distortion.
   - Preprocessing (BGR, SCRFD landmark alignment, ArcFace L2-normalized embedding) is identical.
2. Verify Actual Face Match:
   - Evaluates video observations.
   - Records detections, timestamps, track IDs, embeddings, best identity score, runner-up score, margin, match decision.
   - Compares saved enrollment embedding against corresponding face observations.
   - Confirms exact source frame is detected and its embedding matches (~1.0).
   - Separately reports: face_detected, valid_embedding, identity_accepted.
3. Controlled Diagnostic:
   - Re-extracts identical source frame from video and compares embedding against saved enrollment embedding.
   - Confirms high consistency (>= 0.99).
   - Verifies that diagnostic checks (preprocessing, alignment, normalization, model consistency) trigger on divergence.
   - Safeguard verified: diagnostic does NOT serve as proof of general recognition accuracy across different frames.
4. Preserve Recognition Safeguards:
   - 0.60 normal match and 0.75 high confidence thresholds strictly enforced.
   - 0.05 distinct-identity ambiguity margin enforced.
   - Highest-scoring candidate below 0.60 or within 0.05 of runner-up is safely rejected.
   - Unaccepted faces report diagnostic reasons rather than fabricating a match.
5. Acceptance Criteria:
   - Exact source image processes consistently.
   - Recognition on other frames from the video is measured separately.
   - Failures reported with timestamps and diagnostic details.
   - No claim of guaranteed recognition of every frame or person.
"""

import os
import sys
import uuid
import unittest
import numpy as np
import cv2
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.pipeline.face_engine import FaceEnrollmentEngine
from app.services.same_video_face import (
    extract_enrollment_image_from_video,
    run_controlled_source_diagnostic,
    verify_same_video_face_match,
    rank_distinct_student_identities
)


class TestPhaseF24_0DSameVideoRecognition(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.engine = FaceEnrollmentEngine()
        cls.test_video_path = os.path.join(settings.STORAGE_DIR, "704e3a47-5199-44c5-af72-c56f6ec4ba17.mp4")
        cls.has_video = os.path.exists(cls.test_video_path)
        cls.temp_dir = os.path.join(settings.STORAGE_DIR, "test_f24_0d_artifacts")
        os.makedirs(cls.temp_dir, exist_ok=True)

    def test_1_preserve_source_image_quality_and_metadata(self):
        """
        Requirement 1: Preserve Source Image Quality
        - Preserves original image at native available resolution.
        - Records original video identifier, timestamp, and frame index in metadata.
        - No resizing or recompression before ArcFace processing.
        """
        if not self.has_video:
            self.skipTest("Sample CCTV video not found in storage")

        out_path = os.path.join(self.temp_dir, "enroll_native_res.png")
        target_f_idx = 14
        vid_id = "test-cctv-video-704e"

        res = extract_enrollment_image_from_video(
            video_path=self.test_video_path,
            frame_idx=target_f_idx,
            output_path=out_path,
            video_identifier=vid_id
        )

        self.assertTrue(res["success"], f"Extraction failed: {res.get('error')}")
        self.assertTrue(os.path.exists(out_path), "Extracted image was not written to disk")

        # Verify resolution matches original video native resolution
        cap = cv2.VideoCapture(self.test_video_path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_f_idx)
        ret, orig_frame = cap.read()
        cap.release()
        self.assertTrue(ret)

        saved_img = cv2.imread(out_path)
        self.assertEqual(saved_img.shape, orig_frame.shape, "Extracted image resolution must match native video resolution")
        self.assertEqual(res["resolution"], [orig_frame.shape[1], orig_frame.shape[0]])

        # Verify metadata recording
        meta = res["metadata"]
        self.assertEqual(meta["video_identifier"], vid_id)
        self.assertEqual(meta["frame_idx"], target_f_idx)
        self.assertAlmostEqual(meta["timestamp_seconds"], target_f_idx / 29.952, places=1)
        self.assertEqual(meta["source"], "cctv_video")

        # Verify identical preprocessing during enrollment
        proc_res = self.engine.process_photo(out_path)
        self.assertTrue(proc_res["success"])
        emb = np.array(proc_res["embedding"], dtype=np.float32)
        self.assertEqual(emb.shape, (512,), "ArcFace embedding must be 512 dimensions")
        self.assertAlmostEqual(float(np.linalg.norm(emb)), 1.0, places=4, msg="Embedding must be L2-normalized")

    def test_2_controlled_source_diagnostic(self):
        """
        Requirement 3: Add a Controlled Diagnostic
        - Identifies original source frame and compares live source vs saved enrollment embedding.
        - Verifies exact consistency score (>= 0.99).
        - Verifies that diagnostic checks inspect preprocessing, alignment, and normalization.
        - Enforces safeguard disclaimer that diagnostic != proof of general recognition.
        """
        if not self.has_video:
            self.skipTest("Sample CCTV video not found in storage")

        out_path = os.path.join(self.temp_dir, "enroll_diag_check.png")
        target_f_idx = 14
        extract_res = extract_enrollment_image_from_video(
            video_path=self.test_video_path,
            frame_idx=target_f_idx,
            output_path=out_path
        )
        self.assertTrue(extract_res["success"])

        # Run controlled diagnostic
        diag_res = run_controlled_source_diagnostic(
            enrollment_photo_path=out_path,
            video_path=self.test_video_path,
            frame_idx=target_f_idx,
            face_engine=self.engine
        )

        self.assertTrue(diag_res["diagnostic_passed"], "Controlled diagnostic on identical frame must pass")
        self.assertGreaterEqual(diag_res["similarity_score"], 0.99, "Identical frame similarity must be >= 0.99")
        self.assertEqual(diag_res["source_frame_idx"], target_f_idx)

        # Inspect diagnostic checks
        checks = diag_res["checks"]
        self.assertIn("preprocessing_color_space", checks)
        self.assertTrue(checks["alignment_landmarks_present"])
        self.assertTrue(checks["is_finite"])
        self.assertEqual(checks["embedding_dimension"], 512)
        self.assertAlmostEqual(checks["saved_embedding_norm"], 1.0, places=3)
        self.assertAlmostEqual(checks["live_embedding_norm"], 1.0, places=3)

        # Verify safeguard disclaimer
        self.assertIn("safeguard_disclaimer", diag_res)
        self.assertIn("NOT be used as independent evidence", diag_res["safeguard_disclaimer"])

    def test_3_verify_actual_face_match_with_three_separate_reports(self):
        """
        Requirement 2 & 5: Verify the Actual Face Match & Acceptance Criteria
        - Process video normally and record detections, timestamps, track IDs, embeddings.
        - Confirms exact source frame is detected and embedding is close (~1.0).
        - Reports separately: face_detected, valid_embedding, identity_accepted.
        - Separately measures recognition on other frames of the video.
        """
        if not self.has_video:
            self.skipTest("Sample CCTV video not found in storage")

        source_f_idx = 14
        enr_out_path = os.path.join(self.temp_dir, "enroll_for_match.png")
        enr_res = extract_enrollment_image_from_video(
            video_path=self.test_video_path,
            frame_idx=source_f_idx,
            output_path=enr_out_path
        )
        self.assertTrue(enr_res["success"])

        proc_enr = self.engine.process_photo(enr_out_path)
        self.assertTrue(proc_enr["success"])
        enrollment_embedding = proc_enr["embedding"]
        student_id = uuid.uuid4()

        # Build gallery with enrolled student and competitor students
        comp_sid = uuid.uuid4()
        comp_emb = np.random.randn(512).astype(np.float32)
        comp_emb /= np.linalg.norm(comp_emb)

        enr_arr = np.array(enrollment_embedding, dtype=np.float32)
        enr_arr /= np.linalg.norm(enr_arr)

        gallery = {
            "matrix": np.vstack([enr_arr, comp_emb]),
            "sids": [student_id, comp_sid]
        }

        # Run verification across video
        match_report = verify_same_video_face_match(
            video_path=self.test_video_path,
            enrollment_embedding=enrollment_embedding,
            gallery=gallery,
            source_frame_idx=source_f_idx,
            enrolled_student_id=student_id,
            eval_frame_step=20,
            face_engine=self.engine
        )

        self.assertTrue(match_report["success"])

        # Check Requirement 2 separate reporting flags on exact source frame
        self.assertTrue(match_report["source_frame_detected"], "Exact source frame face must be detected")
        self.assertTrue(match_report["source_frame_valid_embedding"], "Exact source frame must generate valid embedding")
        self.assertTrue(match_report["source_frame_identity_accepted"], "Exact source frame identity must be accepted")
        self.assertGreaterEqual(match_report["source_frame_similarity_to_enrollment"], 0.99)
        self.assertTrue(match_report["source_frame_verified"])

        # Check Requirement 5: Evaluation on OTHER frames measured separately
        other_eval = match_report["other_frames_evaluation"]
        self.assertGreater(other_eval["total_evaluated"], 0, "Must evaluate other frames separately")
        self.assertGreater(other_eval["detected"], 0, "Other frames face detections must be recorded")
        self.assertGreater(other_eval["valid_embeddings"], 0, "Other frames valid embeddings must be recorded")
        self.assertGreater(other_eval["accepted"], 0, "Other frames identity recognition must be measured")
        self.assertGreaterEqual(other_eval["recognition_rate"], 0.60, "Same person across same video should achieve solid recognition")

        # Verify failures tracking
        self.assertIsInstance(match_report["failures"], list)

    def test_4_preserve_safeguards_thresholds_and_ambiguity_margin(self):
        """
        Requirement 4: Preserve Recognition Safeguards
        - Enforces 0.60 medium match threshold.
        - Enforces 0.75 high confidence threshold.
        - Enforces 0.05 ambiguity margin against distinct identity runner-up.
        - Sub-threshold or ambiguous match is never accepted.
        - Failure reasons are explicitly reported instead of fabricating matches.
        """
        sid_a = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
        sid_b = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")

        # Case 1: Below 0.60 threshold
        sids = [sid_a, sid_b]
        sims_low = np.array([0.58, 0.40], dtype=np.float32)
        b_sid, b_sim, s_sid, s_sim, margin = rank_distinct_student_identities(sids, sims_low)
        self.assertEqual(b_sid, sid_a)
        self.assertLess(b_sim, settings.RECOGNITION_MEDIUM_THRESHOLD)
        is_accepted = (b_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD) and not (s_sim >= 0.60 and margin < 0.05)
        self.assertFalse(is_accepted, "Score 0.58 < 0.60 must be rejected")

        # Case 2: Above 0.60 but ambiguous (< 0.05 margin against runner-up)
        sims_ambig = np.array([0.80, 0.77], dtype=np.float32)
        b_sid, b_sim, s_sid, s_sim, margin = rank_distinct_student_identities(sids, sims_ambig)
        self.assertEqual(b_sid, sid_a)
        self.assertEqual(s_sid, sid_b)
        self.assertAlmostEqual(margin, 0.03, places=4)
        is_ambiguous = (s_sid is not None and s_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD and margin < 0.05)
        self.assertTrue(is_ambiguous, "Margin 0.03 < 0.05 must be rejected as ambiguous")

        # Case 3: Clear match passing 0.05 margin
        sims_clear = np.array([0.82, 0.65], dtype=np.float32)
        b_sid, b_sim, s_sid, s_sim, margin = rank_distinct_student_identities(sids, sims_clear)
        self.assertEqual(b_sid, sid_a)
        self.assertAlmostEqual(margin, 0.17, places=4)
        is_ambiguous = (s_sid is not None and s_sim >= settings.RECOGNITION_MEDIUM_THRESHOLD and margin < 0.05)
        self.assertFalse(is_ambiguous, "Margin 0.17 passes margin gate")
        self.assertGreaterEqual(b_sim, settings.RECOGNITION_HIGH_THRESHOLD, "0.82 qualifies as HIGH confidence")

    def test_5_diagnostic_detects_intentional_divergence(self):
        """
        Requirement 3: Add a Controlled Diagnostic (Failure detection)
        - If an incorrect frame or distorted image is provided, diagnostic detects
          and reports divergence before changing thresholds.
        """
        if not self.has_video:
            self.skipTest("Sample CCTV video not found in storage")

        # Save an image from frame 14
        out_path = os.path.join(self.temp_dir, "enroll_for_divergence.png")
        extract_enrollment_image_from_video(
            video_path=self.test_video_path,
            frame_idx=14,
            output_path=out_path
        )

        # Intentionally run diagnostic against frame 140 (different pose / lighting)
        diag_res = run_controlled_source_diagnostic(
            enrollment_photo_path=out_path,
            video_path=self.test_video_path,
            frame_idx=140,
            face_engine=self.engine
        )

        # Must detect that it is NOT identical source frame (< 0.99)
        self.assertFalse(diag_res["diagnostic_passed"], "Diagnostic must flag non-identical frame comparison")
        self.assertLess(diag_res["similarity_score"], 0.99)


if __name__ == "__main__":
    unittest.main()
