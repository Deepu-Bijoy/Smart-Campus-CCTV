"""
Phase F24.0E: Targeted Fight Participant Verification Test Suite.

Covers all 12 required test cases:
1. Successful resolution of both registered students.
2. Missing or ambiguous student records.
3. Violence detected with Ash identified.
4. Violence detected with Jose_John identified.
5. Both students present in the same incident.
6. A student identified but not verified as a fight participant.
7. Face detection failure.
8. Ambiguous identity rejection.
9. No violence detected.
10. Unknown people in the incident.
11. Distinct-student ranking and existing threshold safeguards.
12. Accurate evidence timestamps and incident-report output.
"""

import sys
import os
import json
import uuid
import unittest
import numpy as np
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.services.targeted_verification import (
    rank_distinct_student_identities,
    resolve_target_student,
    evaluate_student_in_tracks,
    perform_targeted_fight_verification
)
from app.schemas.violence import (
    StudentVerificationResult,
    TargetedParticipantVerification
)


class TestTargetedParticipantVerificationSuite(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.ash_id = uuid.UUID("aaaaaaaa-1111-4aaa-aaaa-aaaaaaaaaaaa")
        self.jj_id = uuid.UUID("bbbbbbbb-2222-4bbb-bbbb-bbbbbbbbbbbb")
        self.other_id = uuid.UUID("cccccccc-3333-4ccc-cccc-cccccccccccc")

        # Deterministic normalized 512-dim embedding vectors
        np.random.seed(42)
        v_a = np.random.randn(512).astype(np.float32)
        self.ash_vec = v_a / np.linalg.norm(v_a)

        v_b = np.random.randn(512).astype(np.float32)
        self.jj_vec = v_b / np.linalg.norm(v_b)

        v_c = np.random.randn(512).astype(np.float32)
        self.other_vec = v_c / np.linalg.norm(v_c)

    # 1. Successful resolution of both registered students
    async def test_1_successful_resolution_of_both_registered_students(self):
        mock_student_ash = MagicMock()
        mock_student_ash.id = self.ash_id
        mock_student_ash.name = "Ash"
        mock_student_ash.university_roll_number = "46"

        mock_student_jj = MagicMock()
        mock_student_jj.id = self.jj_id
        mock_student_jj.name = "Jose_John"
        mock_student_jj.university_roll_number = "35"

        mock_db = AsyncMock()

        student_queries = [0]
        # Mock execute returning students and their embeddings
        def mock_execute_side_effect(stmt):
            res = MagicMock()
            sql_str = str(stmt).lower()
            if "students" in sql_str:
                if student_queries[0] == 0:
                    student_queries[0] += 1
                    res.scalars.return_value.all.return_value = [mock_student_ash]
                else:
                    res.scalars.return_value.all.return_value = [mock_student_jj]
            elif "student_face_embeddings" in sql_str:
                mock_emb = MagicMock(embedding=self.ash_vec.tolist())
                res.scalars.return_value.all.return_value = [mock_emb]
            return res

        mock_db.execute.side_effect = mock_execute_side_effect

        ash_res = await resolve_target_student(mock_db, "Ash")
        jj_res = await resolve_target_student(mock_db, "Jose_John")

        self.assertEqual(ash_res["status"], "RESOLVED_VALID_EMBEDDING")
        self.assertEqual(ash_res["student"].name, "Ash")
        self.assertEqual(len(ash_res["embeddings"]), 1)
        self.assertEqual(ash_res["embeddings"][0].shape, (512,))

        self.assertEqual(jj_res["status"], "RESOLVED_VALID_EMBEDDING")
        self.assertEqual(jj_res["student"].name, "Jose_John")
        self.assertEqual(len(jj_res["embeddings"]), 1)
        self.assertIsNone(ash_res["error"])
        self.assertIsNone(jj_res["error"])

    # 2. Missing or ambiguous student records
    async def test_2_missing_or_ambiguous_student_records(self):
        mock_db = AsyncMock()

        # Case 2A: Student not found
        res_empty = MagicMock()
        res_empty.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = res_empty

        missing_res = await resolve_target_student(mock_db, "Unknown_Student")
        self.assertEqual(missing_res["status"], "STUDENT_NOT_FOUND")
        self.assertIn("not found", missing_res["error"].lower())

        # Case 2B: Ambiguous duplicate students
        mock_s1 = MagicMock(id=uuid.uuid4(), name="Ash", university_roll_number="46")
        mock_s2 = MagicMock(id=uuid.uuid4(), name="Ash", university_roll_number="99")
        res_ambig = MagicMock()
        res_ambig.scalars.return_value.all.return_value = [mock_s1, mock_s2]
        mock_db.execute.return_value = res_ambig

        ambig_res = await resolve_target_student(mock_db, "Ash")
        self.assertEqual(ambig_res["status"], "AMBIGUOUS_RECORDS")
        self.assertIn("ambiguous", ambig_res["error"].lower())

        # Case 2C: Record exists but missing embeddings
        mock_s3 = MagicMock(id=uuid.uuid4(), name="Jose_John", university_roll_number="35")
        res_s3 = MagicMock()
        res_s3.scalars.return_value.all.return_value = [mock_s3]

        res_no_emb = MagicMock()
        res_no_emb.scalars.return_value.all.return_value = []

        mock_db.execute.side_effect = [res_s3, res_no_emb, res_no_emb]
        no_emb_res = await resolve_target_student(mock_db, "Jose_John")
        self.assertEqual(no_emb_res["status"], "ENROLLMENT_MISSING_EMBEDDINGS")
        self.assertIn("usable arcface enrollment embeddings", no_emb_res["error"].lower())

    # 3. Violence detected with Ash identified
    def test_3_violence_detected_with_ash_identified(self):
        resolution_ash = {
            "status": "RESOLVED_VALID_EMBEDDING",
            "student": MagicMock(id=self.ash_id, name="Ash"),
            "embeddings": [self.ash_vec]
        }
        intervals = [{"start_time": 10.0, "end_time": 15.0, "confidence": 0.95}]

        # Candidate face matches Ash with sim 0.78, runner-up is other_id at 0.55 (margin 0.23 >= 0.05)
        # Person track is directly engaged in fight
        tracks = {
            1: {
                "start_time": 9.5,
                "end_time": 15.5,
                "detections": [
                    {"frame_number": 100, "timestamp_seconds": 10.5},
                    {"frame_number": 110, "timestamp_seconds": 11.5},
                    {"frame_number": 120, "timestamp_seconds": 12.5},
                    {"frame_number": 130, "timestamp_seconds": 13.5}
                ],
                "candidate_face_crops": [{
                    "face_dims": [24, 28],
                    "det_score": 0.85,
                    "timestamp": 11.5,
                    "frame": 110,
                    "embedding": (self.ash_vec * 0.78 + self.other_vec * 0.22).tolist()
                }]
            }
        }
        cand_emb = np.array(tracks[1]["candidate_face_crops"][0]["embedding"], dtype=np.float32)
        cand_emb /= np.linalg.norm(cand_emb)
        tracks[1]["candidate_face_crops"][0]["embedding"] = cand_emb.tolist()

        gallery_matrix = np.vstack([self.ash_vec, self.other_vec])
        gallery_sids = [self.ash_id, self.other_id]
        diagnostic_failures = []

        result = evaluate_student_in_tracks(
            student_name="Ash",
            resolution=resolution_ash,
            violence_intervals=intervals,
            valid_video_tracks=tracks,
            gallery_matrix=gallery_matrix,
            gallery_sids=gallery_sids,
            diagnostic_failures=diagnostic_failures
        )

        self.assertEqual(result.participation_status, "CONFIRMED_PARTICIPANT")
        self.assertEqual(result.identity_status, "CONFIRMED")
        self.assertGreaterEqual(result.similarity_score, 0.60)
        self.assertEqual(result.best_track_id, "1")
        self.assertEqual(result.best_evidence_timestamp, 11.5)

    # 4. Violence detected with Jose_John identified
    def test_4_violence_detected_with_jose_john_identified(self):
        resolution_jj = {
            "status": "RESOLVED_VALID_EMBEDDING",
            "student": MagicMock(id=self.jj_id, name="Jose_John"),
            "embeddings": [self.jj_vec]
        }
        intervals = [{"start_time": 20.0, "end_time": 25.0, "confidence": 0.90}]

        tracks = {
            2: {
                "start_time": 19.5,
                "end_time": 25.5,
                "detections": [
                    {"frame_number": 200, "timestamp_seconds": 20.5},
                    {"frame_number": 210, "timestamp_seconds": 21.5},
                    {"frame_number": 220, "timestamp_seconds": 22.5},
                    {"frame_number": 230, "timestamp_seconds": 23.5}
                ],
                "candidate_face_crops": [{
                    "face_dims": [20, 24],
                    "det_score": 0.80,
                    "timestamp": 21.5,
                    "frame": 210,
                    "embedding": (self.jj_vec * 0.75 + self.other_vec * 0.25).tolist()
                }]
            }
        }
        cand_emb = np.array(tracks[2]["candidate_face_crops"][0]["embedding"], dtype=np.float32)
        cand_emb /= np.linalg.norm(cand_emb)
        tracks[2]["candidate_face_crops"][0]["embedding"] = cand_emb.tolist()

        gallery_matrix = np.vstack([self.jj_vec, self.other_vec])
        gallery_sids = [self.jj_id, self.other_id]
        diagnostic_failures = []

        result = evaluate_student_in_tracks(
            student_name="Jose_John",
            resolution=resolution_jj,
            violence_intervals=intervals,
            valid_video_tracks=tracks,
            gallery_matrix=gallery_matrix,
            gallery_sids=gallery_sids,
            diagnostic_failures=diagnostic_failures
        )

        self.assertEqual(result.participation_status, "CONFIRMED_PARTICIPANT")
        self.assertEqual(result.identity_status, "CONFIRMED")
        self.assertGreaterEqual(result.similarity_score, 0.60)
        self.assertEqual(result.best_track_id, "2")
        self.assertEqual(result.best_evidence_timestamp, 21.5)

    # 5. Both students present in the same incident
    def test_5_both_students_present_in_same_incident(self):
        resolution_ash = {
            "status": "RESOLVED_VALID_EMBEDDING",
            "student": MagicMock(id=self.ash_id, name="Ash"),
            "embeddings": [self.ash_vec]
        }
        resolution_jj = {
            "status": "RESOLVED_VALID_EMBEDDING",
            "student": MagicMock(id=self.jj_id, name="Jose_John"),
            "embeddings": [self.jj_vec]
        }
        intervals = [{"start_time": 30.0, "end_time": 35.0, "confidence": 0.98}]

        # Track 1 has Ash, Track 2 has Jose_John
        tracks = {
            1: {
                "start_time": 29.0,
                "end_time": 35.0,
                "detections": [{"timestamp_seconds": t} for t in [30.5, 31.5, 32.5, 33.5]],
                "candidate_face_crops": [{
                    "face_dims": [25, 30],
                    "det_score": 0.88,
                    "timestamp": 31.5,
                    "frame": 310,
                    "embedding": (self.ash_vec * 0.80 + self.other_vec * 0.20).tolist()
                }]
            },
            2: {
                "start_time": 29.5,
                "end_time": 35.5,
                "detections": [{"timestamp_seconds": t} for t in [30.5, 31.5, 32.5, 33.5]],
                "candidate_face_crops": [{
                    "face_dims": [22, 26],
                    "det_score": 0.82,
                    "timestamp": 32.0,
                    "frame": 320,
                    "embedding": (self.jj_vec * 0.77 + self.other_vec * 0.23).tolist()
                }]
            }
        }
        for tid in [1, 2]:
            e = np.array(tracks[tid]["candidate_face_crops"][0]["embedding"], dtype=np.float32)
            tracks[tid]["candidate_face_crops"][0]["embedding"] = (e / np.linalg.norm(e)).tolist()

        gallery_matrix = np.vstack([self.ash_vec, self.jj_vec, self.other_vec])
        gallery_sids = [self.ash_id, self.jj_id, self.other_id]
        failures = []

        res_ash = evaluate_student_in_tracks("Ash", resolution_ash, intervals, tracks, gallery_matrix, gallery_sids, failures)
        res_jj = evaluate_student_in_tracks("Jose_John", resolution_jj, intervals, tracks, gallery_matrix, gallery_sids, failures)

        self.assertEqual(res_ash.participation_status, "CONFIRMED_PARTICIPANT")
        self.assertEqual(res_jj.participation_status, "CONFIRMED_PARTICIPANT")
        self.assertEqual(res_ash.best_track_id, "1")
        self.assertEqual(res_jj.best_track_id, "2")
        self.assertNotEqual(res_ash.best_track_id, res_jj.best_track_id)

    # 6. A student identified but not verified as a fight participant
    def test_6_student_identified_but_not_verified_as_fight_participant(self):
        resolution_ash = {
            "status": "RESOLVED_VALID_EMBEDDING",
            "student": MagicMock(id=self.ash_id, name="Ash"),
            "embeddings": [self.ash_vec]
        }
        intervals = [{"start_time": 10.0, "end_time": 15.0, "confidence": 0.88}]

        # Track 5 is near the incident, but standing apart / bystander (only 1 or 2 detections during fight)
        tracks = {
            5: {
                "start_time": 9.0,
                "end_time": 12.0,
                "detections": [
                    {"frame_number": 90, "timestamp_seconds": 9.0},
                    {"frame_number": 100, "timestamp_seconds": 10.2}
                ],
                "candidate_face_crops": [{
                    "face_dims": [22, 26],
                    "det_score": 0.80,
                    "timestamp": 10.2,
                    "frame": 100,
                    "embedding": (self.ash_vec * 0.76 + self.other_vec * 0.24).tolist()
                }]
            }
        }
        e = np.array(tracks[5]["candidate_face_crops"][0]["embedding"], dtype=np.float32)
        tracks[5]["candidate_face_crops"][0]["embedding"] = (e / np.linalg.norm(e)).tolist()

        gallery_matrix = np.vstack([self.ash_vec, self.other_vec])
        gallery_sids = [self.ash_id, self.other_id]
        failures = []

        result = evaluate_student_in_tracks("Ash", resolution_ash, intervals, tracks, gallery_matrix, gallery_sids, failures)

        self.assertEqual(result.identity_status, "CONFIRMED")
        self.assertEqual(result.participation_status, "IDENTIFIED_NEAR_INCIDENT")
        self.assertIn("bystander", result.explanation.lower())

    # 7. Face detection failure
    def test_7_face_detection_failure(self):
        resolution_ash = {
            "status": "RESOLVED_VALID_EMBEDDING",
            "student": MagicMock(id=self.ash_id, name="Ash"),
            "embeddings": [self.ash_vec]
        }
        intervals = [{"start_time": 10.0, "end_time": 15.0, "confidence": 0.90}]

        # Face is turned away / tiny (8x9 px) or low confidence (0.25)
        tracks = {
            1: {
                "start_time": 10.0,
                "end_time": 14.0,
                "detections": [{"timestamp_seconds": 11.0}],
                "candidate_face_crops": [{
                    "face_dims": [8, 9],
                    "det_score": 0.25,
                    "timestamp": 11.0,
                    "frame": 110,
                    "embedding": None
                }]
            }
        }
        failures = []
        result = evaluate_student_in_tracks("Ash", resolution_ash, intervals, tracks, None, [], failures)

        self.assertEqual(result.identity_status, "NOT_OBSERVED")
        self.assertEqual(result.participation_status, "NOT_OBSERVED_IN_INCIDENT")
        self.assertTrue(len(failures) > 0)
        self.assertEqual(failures[0]["status"], "FACE_NOT_USABLE")
        self.assertIn("too small", failures[0]["reason"].lower())

    # 8. Ambiguous identity rejection
    def test_8_ambiguous_identity_rejection(self):
        resolution_ash = {
            "status": "RESOLVED_VALID_EMBEDDING",
            "student": MagicMock(id=self.ash_id, name="Ash"),
            "embeddings": [self.ash_vec]
        }
        intervals = [{"start_time": 10.0, "end_time": 15.0, "confidence": 0.90}]

        # Candidate vector is nearly halfway between Ash and competitor
        # Ash scores 0.68, Competitor scores 0.66 (margin 0.02 < 0.05)
        comb = self.ash_vec * 0.50 + self.other_vec * 0.48
        comb /= np.linalg.norm(comb)

        tracks = {
            1: {
                "start_time": 10.0,
                "end_time": 15.0,
                "detections": [{"timestamp_seconds": t} for t in [10.5, 11.5, 12.5, 13.5]],
                "candidate_face_crops": [{
                    "face_dims": [20, 25],
                    "det_score": 0.85,
                    "timestamp": 11.5,
                    "frame": 115,
                    "embedding": comb.tolist()
                }]
            }
        }
        gallery_matrix = np.vstack([self.ash_vec, self.other_vec])
        gallery_sids = [self.ash_id, self.other_id]
        failures = []

        result = evaluate_student_in_tracks("Ash", resolution_ash, intervals, tracks, gallery_matrix, gallery_sids, failures)

        self.assertEqual(result.identity_status, "AMBIGUOUS")
        self.assertEqual(result.participation_status, "POSSIBLE_PARTICIPANT_UNVERIFIED")
        self.assertLess(result.margin, 0.05)
        self.assertIn("ambiguous", result.explanation.lower())

    # 9. No violence detected
    def test_9_no_violence_detected(self):
        resolution_ash = {
            "status": "RESOLVED_VALID_EMBEDDING",
            "student": MagicMock(id=self.ash_id, name="Ash"),
            "embeddings": [self.ash_vec]
        }
        result = evaluate_student_in_tracks("Ash", resolution_ash, [], {}, None, [], [])

        self.assertEqual(result.participation_status, "NO_VIOLENCE_DETECTED")
        self.assertIn("no violent", result.explanation.lower())

    # 10. Unknown people in the incident
    def test_10_unknown_people_in_the_incident(self):
        resolution_ash = {
            "status": "RESOLVED_VALID_EMBEDDING",
            "student": MagicMock(id=self.ash_id, name="Ash"),
            "embeddings": [self.ash_vec]
        }
        intervals = [{"start_time": 10.0, "end_time": 15.0, "confidence": 0.90}]

        # Track has an unknown person whose embedding has very low similarity to Ash (0.15)
        v_rand = np.random.randn(512).astype(np.float32)
        v_rand /= np.linalg.norm(v_rand)

        tracks = {
            1: {
                "start_time": 10.0,
                "end_time": 15.0,
                "detections": [{"timestamp_seconds": t} for t in [10.5, 11.5, 12.5, 13.5]],
                "candidate_face_crops": [{
                    "face_dims": [22, 26],
                    "det_score": 0.85,
                    "timestamp": 11.5,
                    "frame": 115,
                    "embedding": v_rand.tolist()
                }]
            }
        }
        failures = []
        result = evaluate_student_in_tracks("Ash", resolution_ash, intervals, tracks, None, [], failures)

        self.assertIn(result.participation_status, ["IDENTITY_UNRESOLVED", "NOT_OBSERVED_IN_INCIDENT"])
        self.assertLess(result.similarity_score or 0.0, 0.60)

    # 11. Distinct-student ranking and existing threshold safeguards
    def test_11_distinct_student_ranking_and_existing_threshold_safeguards(self):
        # Multi-photo grouping
        db_sids = [self.ash_id, self.ash_id, self.ash_id, self.jj_id]
        sims = np.array([0.82, 0.80, 0.79, 0.78], dtype=np.float32)

        best_sid, best_sim, sec_sid, sec_sim, margin = rank_distinct_student_identities(db_sids, sims)
        self.assertEqual(best_sid, self.ash_id)
        self.assertAlmostEqual(best_sim, 0.82, places=3)
        self.assertEqual(sec_sid, self.jj_id)
        self.assertAlmostEqual(sec_sim, 0.78, places=3)
        self.assertAlmostEqual(margin, 0.04, places=3)

        # Margin gate rejects 0.04 < 0.05
        is_ambiguous = (sec_sid is not None and str(sec_sid) != str(best_sid) and margin < 0.05)
        self.assertTrue(is_ambiguous)

        # Sub-threshold rejection (0.58 < 0.60)
        sims_sub = np.array([0.58, 0.50, 0.40, 0.30], dtype=np.float32)
        b_sid, b_sim, _, _, _ = rank_distinct_student_identities(db_sids, sims_sub)
        self.assertLess(b_sim, settings.RECOGNITION_MEDIUM_THRESHOLD)

    # 12. Accurate evidence timestamps and incident-report output
    async def test_12_accurate_evidence_timestamps_and_incident_report_output(self):
        mock_db = AsyncMock()

        mock_s_ash = MagicMock()
        mock_s_ash.id = self.ash_id
        mock_s_ash.name = "Ash"
        mock_s_ash.university_roll_number = "46"

        mock_s_jj = MagicMock()
        mock_s_jj.id = self.jj_id
        mock_s_jj.name = "Jose_John"
        mock_s_jj.university_roll_number = "35"

        def mock_exec(stmt):
            res = MagicMock()
            s_str = str(stmt).lower()
            params = {}
            try:
                params = stmt.compile().params
            except Exception:
                pass
            param_vals = [str(v).lower() for v in params.values()]

            if "students" in s_str and "student_face_embeddings" not in s_str:
                if any("ash" in v for v in param_vals):
                    res.scalars.return_value.all.return_value = [mock_s_ash]
                else:
                    res.scalars.return_value.all.return_value = [mock_s_jj]
            elif "student_face_embeddings" in s_str:
                if any(str(self.ash_id).lower() in v for v in param_vals):
                    res.scalars.return_value.all.return_value = [MagicMock(embedding=self.ash_vec.tolist())]
                elif any(str(self.jj_id).lower() in v for v in param_vals):
                    res.scalars.return_value.all.return_value = [MagicMock(embedding=self.jj_vec.tolist())]
                else:
                    res.scalars.return_value.all.return_value = []

                res.fetchall.return_value = [
                    (self.ash_id, json.dumps(self.ash_vec.tolist())),
                    (self.jj_id, json.dumps(self.jj_vec.tolist()))
                ]
            return res

        mock_db.execute.side_effect = mock_exec

        video_id = uuid.uuid4()
        violence_segs = [MagicMock(start_time=343.0, end_time=348.0, confidence=0.99)]
        tracks = {
            1: {
                "start_time": 342.0,
                "end_time": 348.0,
                "detections": [{"timestamp_seconds": t} for t in [343.0, 344.0, 345.0, 346.0]],
                "candidate_face_crops": [{
                    "face_dims": [24, 28],
                    "det_score": 0.85,
                    "timestamp": 344.5,
                    "frame": 8612,
                    "embedding": self.ash_vec.tolist()
                }]
            }
        }

        report = await perform_targeted_fight_verification(
            db=mock_db,
            video_id=video_id,
            video_filename="My Video-1.mp4",
            violence_segments=violence_segs,
            valid_video_tracks=tracks
        )

        self.assertIsInstance(report, TargetedParticipantVerification)
        self.assertEqual(report.video_id, str(video_id))
        self.assertEqual(report.video_filename, "My Video-1.mp4")
        self.assertTrue(report.violence_detected)
        self.assertEqual(len(report.violence_intervals), 1)
        self.assertEqual(report.violence_intervals[0]["start_time"], 343.0)
        self.assertEqual(report.violence_intervals[0]["end_time"], 348.0)

        # Ash verified with accurate evidence timestamp and frame
        self.assertEqual(report.ash.student_name, "Ash")
        self.assertEqual(report.ash.participation_status, "CONFIRMED_PARTICIPANT")
        self.assertEqual(report.ash.best_evidence_timestamp, 344.5)
        self.assertEqual(report.ash.best_evidence_frame, 8612)
        self.assertEqual(report.ash.best_track_id, "1")

        # Jose_John observed status
        self.assertEqual(report.jose_john.student_name, "Jose_John")
        self.assertIn(report.jose_john.participation_status, ["NOT_OBSERVED_IN_INCIDENT", "IDENTITY_UNRESOLVED"])


if __name__ == "__main__":
    unittest.main()
