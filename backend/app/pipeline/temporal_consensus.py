"""
Temporal Face Recognition and Consensus Engine.
Track-level observation pooling, biometric quality ranking,
temporal consensus aggregation, contradictory identity rejection, failure telemetry,
and pre-incident face recovery.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional, Any
import uuid
import numpy as np
import cv2
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class FaceObservation:
    """A single detected face observation associated with a person track."""
    embedding: np.ndarray             # 512-dim float32 unit-normalized vector
    frame: int                        # Video frame index
    timestamp: float                  # Timestamp in seconds
    face_bbox: List[int]              # [x1, y1, x2, y2] in frame coordinates
    person_bbox: List[int]            # [px1, py1, px2, py2] in frame coordinates
    det_score: float                  # Detector confidence
    blur_score: float                 # Laplacian variance sharpness
    face_dims: Tuple[int, int]        # (width, height) in pixels
    quality_score: float              # Deterministic biometric quality in [0, 1]
    crop_path: Optional[str] = None   # File path to cropped thumbnail
    source: str = "head_crop"         # "head_crop", "altercation_tile", "body_crop", "pre_incident"
    is_pre_incident: bool = False     # Whether captured before altercation window
    quality_category: str = "FACE_SUITABLE_FOR_RECOGNITION"
    failure_reason: Optional[str] = None
    pose: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    top_sid: Optional[uuid.UUID] = None
    top_sim: float = 0.0
    second_sid: Optional[uuid.UUID] = None
    second_sim: float = 0.0
    margin: float = 0.0


@dataclass
class TrackObservationPool:
    """
    Sliding observation reservoir for a single ByteTrack person track.
    Enforces capacity bounds, temporal diversity (minimum frame gap), and quality retention.
    """
    trk_id: int
    max_capacity: int = 6
    min_frame_gap: int = 6
    observations: List[FaceObservation] = field(default_factory=list)

    def __post_init__(self):
        # Override with centralized settings if defaults were provided
        if self.max_capacity == 6:
            self.max_capacity = getattr(settings, "FACE_OBSERVATION_POOL_CAPACITY", 6)
        if self.min_frame_gap == 6:
            self.min_frame_gap = getattr(settings, "FACE_OBSERVATION_MIN_FRAME_GAP", 6)

    def add_observation(self, obs: FaceObservation) -> bool:
        """
        Adds a face observation to the reservoir while enforcing temporal separation
        and quality-based replacement.
        """
        if obs is None or obs.embedding is None or len(obs.embedding) != 512:
            return False

        # Ensure unit norm
        norm = float(np.linalg.norm(obs.embedding))
        if norm > 0 and abs(norm - 1.0) > 1e-4:
            obs.embedding = (obs.embedding / norm).astype(np.float32)

        # 1. Temporal separation: check if an observation from an adjacent frame already exists
        for i, existing in enumerate(self.observations):
            if abs(existing.frame - obs.frame) < self.min_frame_gap:
                # Replace only if new observation has strictly higher biometric quality
                if obs.quality_score > existing.quality_score:
                    self.observations[i] = obs
                    self.observations.sort(key=lambda o: o.quality_score, reverse=True)
                    return True
                return False

        # 2. Capacity management
        if len(self.observations) < self.max_capacity:
            self.observations.append(obs)
            self.observations.sort(key=lambda o: o.quality_score, reverse=True)
            return True
        else:
            # Replace lowest-quality observation if new observation has higher quality
            min_idx = min(range(len(self.observations)), key=lambda i: self.observations[i].quality_score)
            if obs.quality_score > self.observations[min_idx].quality_score:
                self.observations[min_idx] = obs
                self.observations.sort(key=lambda o: o.quality_score, reverse=True)
                return True

        return False

    def get_top_k(self, k: int = 3) -> List[FaceObservation]:
        """Returns the top-K highest quality observations."""
        return self.observations[:k]


@dataclass
class ConsensusResult:
    """Result of temporal consensus identity evaluation for a track."""
    status: str                       # "IDENTIFIED", "UNIDENTIFIED", "AMBIGUOUS", "CONTRADICTORY", "NO_FACE"
    student_id: Optional[uuid.UUID] = None
    student_name: Optional[str] = None
    student_obj: Optional[Any] = None
    similarity_score: float = 0.0
    confidence: str = "unidentified"  # "high", "medium", "unidentified"
    second_student_id: Optional[uuid.UUID] = None
    second_similarity: float = 0.0
    margin: float = 0.0
    vote_weight: float = 0.0
    supporting_observations_count: int = 0
    total_observations_count: int = 0
    best_crop_path: Optional[str] = None
    medoid_embedding: Optional[List[float]] = None
    rejection_reason: Optional[str] = None
    quality_category: Optional[str] = None
    failure_category: Optional[str] = None
    observations: List[Dict[str, Any]] = field(default_factory=list)


class TemporalConsensusEngine:
    """
    Evaluates temporal face consensus across track-level observation pools:
    - Computes multi-attribute biometric quality ranking.
    - Executes quality-weighted identity voting.
    - Identifies and rejects contradictory identity predictions.
    - Computes medoid and quality-weighted composite embeddings.
    - Preserves strict safety thresholds (>= 0.60, ambiguity margin >= 0.05).
    - Produces fine-grained failure telemetry.
    """

    @staticmethod
    def compute_biometric_quality(
        det_score: float,
        blur_score: float,
        fw: int,
        fh: int,
        person_bbox: Optional[List[int]] = None,
        face_bbox: Optional[List[int]] = None
    ) -> float:
        """
        Calculates a deterministic biometric quality score Q in [0, 1] incorporating:
        - Detector confidence (0.35 to 0.95)
        - Face pixel resolution (12px to 60px)
        - Laplacian variance sharpness (10 to 250)
        - Spatial centrality and upright aspect ratio consistency
        """
        try:
            conf = float(det_score) if det_score is not None else 0.0
            norm_conf = float(np.clip((conf - 0.35) / 0.60, 0.0, 1.0))

            face_dim = float(np.sqrt(max(0, fw * fh)))
            norm_size = float(np.clip((face_dim - 12.0) / 48.0, 0.15, 1.0))

            blur_val = float(blur_score) if blur_score is not None else 0.0
            norm_sharp = float(np.clip(np.log1p(max(0.0, blur_val)) / np.log1p(250.0), 0.10, 1.0))

            # Bounding box centrality & aspect ratio consistency
            norm_pose = 1.0
            if person_bbox and face_bbox and len(person_bbox) == 4 and len(face_bbox) == 4:
                px1, py1, px2, py2 = person_bbox
                fx1, fy1, fx2, fy2 = face_bbox
                pw = max(1.0, float(px2 - px1))
                fcx = (fx1 + fx2) / 2.0
                pcx = (px1 + px2) / 2.0
                dist_center = abs(fcx - pcx) / pw
                norm_pose = float(np.clip(1.0 - 1.2 * dist_center, 0.40, 1.0))

                aspect = float(fh) / max(1.0, float(fw))
                if aspect < 0.70 or aspect > 1.60:
                    norm_pose *= 0.75

            # Multi-attribute weighted combination
            q = (norm_conf ** 0.35) * (norm_size ** 0.30) * (norm_sharp ** 0.20) * (norm_pose ** 0.15)
            return float(round(np.clip(q, 0.0, 1.0), 4))
        except Exception as e:
            logger.debug("Failed computing biometric quality: %s", e)
            return float(round(max(0.0, min(1.0, float(det_score or 0.0))), 4))

    @staticmethod
    def rank_distinct_student_identities(
        db_sids: List[Any],
        sims: np.ndarray
    ) -> Tuple[Optional[Any], float, Optional[Any], float, float]:
        """
        Groups gallery similarities by distinct student UUID and computes the top-1 to runner-up margin.
        Returns: (best_sid, best_sim, second_sid, second_sim, margin)
        """
        if db_sids is None or sims is None or len(db_sids) == 0 or len(sims) == 0:
            return None, 0.0, None, 0.0, 0.0

        student_max: Dict[str, Tuple[Any, float]] = {}
        for sid, s_val in zip(db_sids, sims):
            if sid is None:
                continue
            try:
                val = float(s_val)
            except (TypeError, ValueError):
                continue
            if not np.isfinite(val):
                continue

            sid_key = str(sid)
            if sid_key not in student_max or val > student_max[sid_key][1]:
                student_max[sid_key] = (sid, val)

        if not student_max:
            return None, 0.0, None, 0.0, 0.0

        ranked = sorted(student_max.values(), key=lambda item: item[1], reverse=True)
        best_sid, best_sim = ranked[0]

        if len(ranked) > 1:
            second_sid, second_sim = ranked[1]
            margin = float(best_sim - second_sim)
        else:
            second_sid, second_sim = None, 0.0
            margin = float(best_sim)

        return best_sid, float(best_sim), second_sid, float(second_sim), float(margin)

    def evaluate_track_consensus(
        self,
        pool: TrackObservationPool,
        gallery_matrix: Optional[np.ndarray],
        gallery_sids: List[uuid.UUID],
        enrolled_students_map: Dict[uuid.UUID, Any],
        medium_threshold: Optional[float] = None,
        high_threshold: Optional[float] = None,
        ambiguity_margin: Optional[float] = None,
        track_failure_info: Optional[Dict[str, Any]] = None
    ) -> ConsensusResult:
        """
        Evaluates temporal identity consensus across all observations in the pool:
        1. Compares each observation against the gallery matrix.
        2. Aggregates quality-weighted identity votes.
        3. Detects and rejects contradictory identity evidence.
        4. Verifies composite / medoid embedding consistency.
        5. Enforces strict recognition thresholds (>= 0.60) and ambiguity margins (>= 0.05).
        6. Preserves detailed failure categorization for unconfirmed tracks.
        """
        if medium_threshold is None:
            medium_threshold = getattr(settings, "RECOGNITION_MEDIUM_THRESHOLD", 0.60)
        if high_threshold is None:
            high_threshold = getattr(settings, "RECOGNITION_HIGH_THRESHOLD", 0.75)
        if ambiguity_margin is None:
            ambiguity_margin = getattr(settings, "FACE_AMBIGUITY_MARGIN", 0.05)

        if not pool.observations:
            fail_cat = "NO_FACE_DETECTED"
            fail_msg = "No face observations available for track"
            if track_failure_info:
                fail_cat = track_failure_info.get("quality_category", fail_cat)
                fail_msg = track_failure_info.get("failure_reason", fail_msg)
            return ConsensusResult(
                status="NO_FACE",
                rejection_reason=fail_msg,
                quality_category=fail_cat,
                failure_category=fail_cat
            )

        if gallery_matrix is None or len(gallery_sids) == 0 or gallery_matrix.shape[0] == 0:
            # No gallery embeddings to compare against
            best_obs = max(pool.observations, key=lambda o: o.quality_score)
            return ConsensusResult(
                status="UNIDENTIFIED",
                best_crop_path=best_obs.crop_path,
                rejection_reason="No enrolled student embeddings available in gallery",
                quality_category=best_obs.quality_category,
                total_observations_count=len(pool.observations)
            )

        # 1. Score every observation in the pool against the enrolled gallery
        for obs in pool.observations:
            sims = np.dot(gallery_matrix, obs.embedding)
            top_sid, top_sim, sec_sid, sec_sim, margin = self.rank_distinct_student_identities(gallery_sids, sims)
            obs.top_sid = top_sid
            obs.top_sim = top_sim
            obs.second_sid = sec_sid
            obs.second_sim = sec_sim
            obs.margin = margin

        # 2. Group qualified observations by predicted student identity
        # An observation qualifies only if top_sim >= medium_threshold and margin >= ambiguity_margin
        candidate_votes: Dict[uuid.UUID, Dict[str, Any]] = {}

        for obs in pool.observations:
            if obs.top_sid and obs.top_sim >= medium_threshold and obs.margin >= ambiguity_margin:
                sid = obs.top_sid
                if sid not in candidate_votes:
                    candidate_votes[sid] = {
                        "obs_list": [],
                        "total_weight": 0.0,
                        "peak_sim": 0.0,
                        "second_sid": obs.second_sid,
                        "second_sim": obs.second_sim
                    }
                cv = candidate_votes[sid]
                cv["obs_list"].append(obs)
                cv["total_weight"] += (obs.quality_score * obs.top_sim)
                if obs.top_sim > cv["peak_sim"]:
                    cv["peak_sim"] = obs.top_sim
                    cv["second_sid"] = obs.second_sid
                    cv["second_sim"] = obs.second_sim

        # 3. If no student achieved similarity >= medium_threshold, truthfully report UNIDENTIFIED
        if not candidate_votes:
            best_sub = max(pool.observations, key=lambda o: o.top_sim)
            rejection_reason = (
                f"Peak similarity ({best_sub.top_sim:.4f}) is below recognition threshold ({medium_threshold:.2f})"
                if best_sub.top_sim > 0.0 else "Face observations did not match any enrolled student"
            )
            return ConsensusResult(
                status="UNIDENTIFIED",
                similarity_score=best_sub.top_sim,
                second_similarity=best_sub.second_sim,
                margin=best_sub.margin,
                best_crop_path=best_sub.crop_path,
                total_observations_count=len(pool.observations),
                rejection_reason=rejection_reason,
                quality_category=best_sub.quality_category,
                observations=[{
                    "frame": o.frame,
                    "timestamp": o.timestamp,
                    "similarity": round(o.top_sim, 4),
                    "quality": round(o.quality_score, 4),
                    "quality_category": o.quality_category,
                    "failure_reason": o.failure_reason,
                    "source": o.source,
                    "is_pre_incident": o.is_pre_incident
                } for o in pool.observations]
            )

        # 4. Rank candidate student identities by total vote weight and peak similarity
        ranked_sids = sorted(
            candidate_votes.keys(),
            key=lambda sid: (candidate_votes[sid]["total_weight"], candidate_votes[sid]["peak_sim"]),
            reverse=True
        )

        winning_sid = ranked_sids[0]
        winner_data = candidate_votes[winning_sid]

        # 5. Contradictory Identity Safeguard:
        # If multiple distinct enrolled students received strong votes (>= medium_threshold),
        # verify that the runner-up is not a significant conflicting claim.
        if len(ranked_sids) > 1:
            runner_up_sid = ranked_sids[1]
            runner_up_data = candidate_votes[runner_up_sid]
            weight_ratio = runner_up_data["total_weight"] / max(1e-4, winner_data["total_weight"])
            peak_diff = winner_data["peak_sim"] - runner_up_data["peak_sim"]

            # Contradiction trigger: runner-up has >= 50% of winner's vote weight or within ambiguity margin
            if weight_ratio >= 0.50 or peak_diff < ambiguity_margin:
                logger.info(
                    "[TEMPORAL CONSENSUS] Track %s: Contradictory identities detected (%s vs %s, diff=%.3f, ratio=%.2f). Rejecting.",
                    pool.trk_id, winning_sid, runner_up_sid, peak_diff, weight_ratio
                )
                best_sub = max(pool.observations, key=lambda o: o.quality_score)
                return ConsensusResult(
                    status="CONTRADICTORY",
                    student_id=None,
                    similarity_score=winner_data["peak_sim"],
                    second_student_id=runner_up_sid,
                    second_similarity=runner_up_data["peak_sim"],
                    margin=peak_diff,
                    best_crop_path=best_sub.crop_path,
                    total_observations_count=len(pool.observations),
                    supporting_observations_count=len(winner_data["obs_list"]),
                    rejection_reason=f"Contradictory identity evidence across observations ({winning_sid} vs {runner_up_sid})",
                    quality_category="CONTRADICTORY_IDENTITY",
                    failure_category="CONTRADICTORY_IDENTITY",
                    observations=[{
                        "frame": o.frame,
                        "timestamp": o.timestamp,
                        "similarity": round(o.top_sim, 4),
                        "quality": round(o.quality_score, 4),
                        "quality_category": o.quality_category,
                        "failure_reason": o.failure_reason,
                        "source": o.source,
                        "is_pre_incident": o.is_pre_incident
                    } for o in pool.observations]
                )

        # 6. Quality-Weighted Composite / Medoid Embedding Verification
        winning_obs = winner_data["obs_list"]
        if len(winning_obs) >= 2:
            # Weighted average embedding
            weights = np.array([o.quality_score for o in winning_obs], dtype=np.float32)
            w_sum = float(np.sum(weights))
            if w_sum > 0:
                weights /= w_sum
            else:
                weights = np.ones(len(winning_obs), dtype=np.float32) / len(winning_obs)

            comp_emb = np.sum([o.embedding * w for o, w in zip(winning_obs, weights)], axis=0)
            c_norm = float(np.linalg.norm(comp_emb))
            if c_norm > 0:
                comp_emb /= c_norm

            # Validate composite against gallery
            c_sims = np.dot(gallery_matrix, comp_emb)
            c_best_sid, c_best_sim, c_sec_sid, c_sec_sim, c_margin = self.rank_distinct_student_identities(gallery_sids, c_sims)

            if str(c_best_sid) == str(winning_sid) and c_best_sim >= medium_threshold and c_margin >= ambiguity_margin:
                final_sim = max(c_best_sim, winner_data["peak_sim"])
                final_sec_sid = c_sec_sid
                final_sec_sim = c_sec_sim
                final_margin = c_margin
                rep_embedding = comp_emb
            else:
                # Composite drifted or became ambiguous; rely on peak observation
                final_sim = winner_data["peak_sim"]
                final_sec_sid = winner_data["second_sid"]
                final_sec_sim = winner_data["second_sim"]
                final_margin = float(final_sim - final_sec_sim)
                rep_embedding = max(winning_obs, key=lambda o: o.top_sim).embedding
        else:
            # Single supporting observation: enforce quality gate (Q >= min_quality)
            min_quality_gate = getattr(settings, "FACE_MIN_QUALITY_GATE", 0.20)
            single_o = winning_obs[0]
            if single_o.quality_score < min_quality_gate:
                return ConsensusResult(
                    status="UNIDENTIFIED",
                    similarity_score=single_o.top_sim,
                    second_similarity=single_o.second_sim,
                    margin=single_o.margin,
                    best_crop_path=single_o.crop_path,
                    total_observations_count=len(pool.observations),
                    rejection_reason=f"Single observation biometric quality ({single_o.quality_score:.3f}) below required gate ({min_quality_gate:.2f})",
                    quality_category="FACE_UNSUITABLE_QUALITY",
                    failure_category="FACE_UNSUITABLE_QUALITY",
                    observations=[{
                        "frame": o.frame,
                        "timestamp": o.timestamp,
                        "similarity": round(o.top_sim, 4),
                        "quality": round(o.quality_score, 4),
                        "quality_category": o.quality_category,
                        "failure_reason": o.failure_reason,
                        "source": o.source,
                        "is_pre_incident": o.is_pre_incident
                    } for o in pool.observations]
                )

            final_sim = single_o.top_sim
            final_sec_sid = single_o.second_sid
            final_sec_sim = single_o.second_sim
            final_margin = single_o.margin
            rep_embedding = single_o.embedding

        # 7. Select Primary Representative Crop (Highest Biometric Quality in Consensus Group)
        best_quality_obs = max(winning_obs, key=lambda o: (o.quality_score, o.top_sim))
        student_obj = enrolled_students_map.get(winning_sid)
        confidence = "high" if final_sim >= high_threshold else "medium"

        return ConsensusResult(
            status="IDENTIFIED",
            student_id=winning_sid,
            student_name=student_obj.name if student_obj else str(winning_sid),
            student_obj=student_obj,
            similarity_score=round(float(final_sim), 4),
            confidence=confidence,
            second_student_id=final_sec_sid,
            second_similarity=round(float(final_sec_sim), 4),
            margin=round(float(final_margin), 4),
            vote_weight=round(float(winner_data["total_weight"]), 4),
            supporting_observations_count=len(winning_obs),
            total_observations_count=len(pool.observations),
            best_crop_path=best_quality_obs.crop_path,
            medoid_embedding=rep_embedding.tolist() if isinstance(rep_embedding, np.ndarray) else rep_embedding,
            quality_category="FACE_SUITABLE_FOR_RECOGNITION",
            observations=[{
                "frame": o.frame,
                "timestamp": o.timestamp,
                "similarity": round(o.top_sim, 4),
                "quality": round(o.quality_score, 4),
                "quality_category": o.quality_category,
                "failure_reason": o.failure_reason,
                "source": o.source,
                "is_pre_incident": o.is_pre_incident
            } for o in pool.observations]
        )
