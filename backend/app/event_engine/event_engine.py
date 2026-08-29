import os
import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.camera import VirtualZone, Camera
from app.models.video import Video
from app.models.track import Track, PersonReid
from app.models.recognition import StudentRecognitionEvent
from app.models.incident import Incident, IncidentPerson, Evidence, DetectedEvent
from app.event_engine.zone_analyzer import ZoneAnalyzer
from app.services.clip_generator import generate_subclip
from app.services.vector_store import QdrantVectorStore
from app.pipeline.embedder import CLIPEmbedder

logger = logging.getLogger(__name__)

class BoundaryCrossingDetector:
    """Calculates spatial crossing segment vectors and returns crossing probability."""
    def analyze(self, p1: Tuple[float, float], p2: Tuple[float, float], zone_coords: List[Tuple[float, float]], geometry_type: str) -> float:
        is_crossing = ZoneAnalyzer.does_segment_cross_zone(p1, p2, zone_coords, geometry_type)
        return 1.0 if is_crossing else 0.0

class FightDetector:
    """
    Implements multi-signal scoring for fight incident classification:
    - Motion Dynamics (Velocity)
    - Person Interaction (Proximity)
    - CLIP Text-Image Similarity
    - Temporal Persistence (Track Overlap)
    """
    def analyze(
        self, 
        tracks: List[Track], 
        clip_score: float, 
        match_time_sec: float, 
        time_window: float = 5.0
    ) -> Tuple[float, Dict[str, float]]:
        # 1. Motion Dynamics (40%)
        motion_score = 0.0
        active_tracks = []
        for t in tracks:
            if t.object_class != "person" or len(t.detections) < 2:
                continue
            
            # Check if active in the window
            t_dets = [d for d in t.detections if abs(d.timestamp_seconds - match_time_sec) <= time_window]
            if len(t_dets) >= 2:
                active_tracks.append((t, t_dets))
                
        if active_tracks:
            max_speed = 0.0
            for t, dets in active_tracks:
                dets_sorted = sorted(dets, key=lambda d: d.timestamp_seconds)
                dx = (dets_sorted[-1].bounding_box[0] + dets_sorted[-1].bounding_box[2])/2.0 - \
                     (dets_sorted[0].bounding_box[0] + dets_sorted[0].bounding_box[2])/2.0
                dy = (dets_sorted[-1].bounding_box[1] + dets_sorted[-1].bounding_box[3])/2.0 - \
                     (dets_sorted[0].bounding_box[1] + dets_sorted[0].bounding_box[3])/2.0
                dt = max(0.1, dets_sorted[-1].timestamp_seconds - dets_sorted[0].timestamp_seconds)
                speed = (dx**2 + dy**2)**0.5 / dt
                if speed > max_speed:
                    max_speed = speed
            
            # Scale speed: >5 px/sec or >40 px/sec
            if max_speed >= 20.0:
                motion_score = 1.0
            elif max_speed > 2.0:
                motion_score = (max_speed - 2.0) / 18.0

        # 2. Person Interaction Proximity (30%)
        proximity_score = 0.5 if len(tracks) >= 2 else 0.0
        min_dist = float("inf")
        if len(active_tracks) >= 2:
            for idx1 in range(len(active_tracks)):
                for idx2 in range(idx1 + 1, len(active_tracks)):
                    t1_det = active_tracks[idx1][1][-1]
                    t2_det = active_tracks[idx2][1][-1]
                    
                    c1 = ((t1_det.bounding_box[0] + t1_det.bounding_box[2])/2.0, (t1_det.bounding_box[1] + t1_det.bounding_box[3])/2.0)
                    c2 = ((t2_det.bounding_box[0] + t2_det.bounding_box[2])/2.0, (t2_det.bounding_box[1] + t2_det.bounding_box[3])/2.0)
                    dist = ((c1[0]-c2[0])**2 + (c1[1]-c2[1])**2)**0.5
                    if dist < min_dist:
                        min_dist = dist
            
            if min_dist <= 200.0 or min_dist <= 0.5:
                proximity_score = 1.0
            elif min_dist < 400.0:
                proximity_score = 0.8

        # 3. CLIP Score (20%) - Raw CLIP text-image cosine similarities range from 0.18 to 0.35
        clip_normalized = min(1.0, max(0.0, (clip_score - 0.18) / 0.20))

        # 4. Temporal Persistence (10%)
        persistence_score = 0.5 if len(tracks) >= 2 else 0.0
        if len(active_tracks) >= 2:
            overlaps = []
            for t, dets in active_tracks:
                overlaps.append((dets[0].timestamp_seconds, dets[-1].timestamp_seconds))
            
            max_start = max(o[0] for o in overlaps)
            min_end = min(o[1] for o in overlaps)
            overlap_duration = max(0.0, min_end - max_start)
            persistence_score = min(1.0, max(0.5, overlap_duration / 2.0))

        combined_score = max(
            clip_score * 2.5,
            motion_score * 0.35 +
            proximity_score * 0.35 +
            clip_normalized * 0.20 +
            persistence_score * 0.10
        )
        combined_score = min(0.99, combined_score)
        
        breakdown = {
            "motion_dynamics": motion_score,
            "person_interaction": proximity_score,
            "clip_similarity": clip_normalized,
            "temporal_persistence": persistence_score
        }
        return combined_score, breakdown

class SuspiciousActivityDetector:
    """Calculates suspicious activity probability from motion speed or CLIP embeddings."""
    def analyze(self, track: Track, clip_score: float) -> Tuple[float, Dict[str, float]]:
        motion_score = 0.0
        if len(track.detections) >= 2:
            dets_sorted = sorted(track.detections, key=lambda d: d.timestamp_seconds)
            dx = (dets_sorted[-1].bounding_box[0] + dets_sorted[-1].bounding_box[2])/2.0 - \
                 (dets_sorted[0].bounding_box[0] + dets_sorted[0].bounding_box[2])/2.0
            dy = (dets_sorted[-1].bounding_box[1] + dets_sorted[-1].bounding_box[3])/2.0 - \
                 (dets_sorted[0].bounding_box[1] + dets_sorted[0].bounding_box[3])/2.0
            dt = max(0.1, dets_sorted[-1].timestamp_seconds - dets_sorted[0].timestamp_seconds)
            speed = (dx**2 + dy**2)**0.5 / dt
            
            # Scale speed: >40 px/sec is 1.0, <10 px/sec is 0.0
            if speed >= 40.0:
                motion_score = 1.0
            elif speed > 10.0:
                motion_score = (speed - 10.0) / 30.0
                
        clip_normalized = min(1.0, max(0.0, (clip_score - 0.35) / 0.35))
        
        # 60% CLIP match + 40% Speed
        combined = clip_normalized * 0.60 + motion_score * 0.40
        return combined, {"motion_dynamics": motion_score, "clip_similarity": clip_normalized}

class EventDetectionEngine:
    @staticmethod
    async def process_video_events(
        db: AsyncSession,
        video_id: uuid.UUID,
        camera_id: uuid.UUID
    ) -> int:
        """
        Executes spatial virtual zone crossing checks and semantic queries in Qdrant 
        to identify incidents, links involved students and evidence, and inserts them.
        """
        logger.info(f"Starting modular incident detection for video {video_id} and camera {camera_id}.")
        
        # 1. Fetch Video and Camera details
        video_stmt = select(Video).filter(Video.id == video_id)
        video_res = await db.execute(video_stmt)
        video = video_res.scalars().first()
        if not video:
            logger.error(f"Video {video_id} not found during incident detection.")
            return 0
            
        camera_stmt = select(Camera).filter(Camera.id == camera_id)
        camera_res = await db.execute(camera_stmt)
        camera = camera_res.scalars().first()
        camera_name = camera.name if camera else "Unknown Camera"

        # 2. Fetch virtual zones
        zone_stmt = select(VirtualZone).filter(VirtualZone.camera_id == camera_id)
        zone_res = await db.execute(zone_stmt)
        zones = zone_res.scalars().all()
        
        # 3. Query all tracks
        track_stmt = (
            select(Track)
            .options(selectinload(Track.detections))
            .filter(Track.video_id == video_id)
        )
        track_res = await db.execute(track_stmt)
        tracks = track_res.scalars().all()

        # Initialize classifiers
        boundary_detector = BoundaryCrossingDetector()
        fight_detector = FightDetector()
        suspicious_detector = SuspiciousActivityDetector()

        incidents_created = 0

        # --- A. SPATIAL GEOMETRIC CHECK (Boundary Crossing & Restricted Area Entry) ---
        for track in tracks:
            if len(track.detections) < 2:
                continue
                
            dets = sorted(
                [
                    {
                        "x": (d.bounding_box[0] + d.bounding_box[2]) / 2.0 if (d.bounding_box and len(d.bounding_box) >= 4) else 0.0,
                        "y": (d.bounding_box[1] + d.bounding_box[3]) / 2.0 if (d.bounding_box and len(d.bounding_box) >= 4) else 0.0,
                        "timestamp_seconds": d.timestamp_seconds,
                        "frame": d.frame_number
                    } for d in track.detections
                ],
                key=lambda x: x["timestamp_seconds"]
            )
            
            for i in range(len(dets) - 1):
                p1 = (dets[i]["x"], dets[i]["y"])
                p2 = (dets[i+1]["x"], dets[i+1]["y"])
                
                for zone in zones:
                    zone_coords = ZoneAnalyzer.parse_coordinates(zone.coordinates)
                    if not zone_coords:
                        continue
                        
                    prob = boundary_detector.analyze(p1, p2, zone_coords, zone.geometry_type)
                    if prob > 0.5:
                        t_sec = dets[i]["timestamp_seconds"]
                        incident_time = video.created_at + timedelta(seconds=t_sec)
                        
                        if zone.zone_type.lower() == 'fence' or 'fence' in zone.name.lower() or 'wall' in zone.name.lower():
                            inc_type = "Boundary Crossing"
                            explanation = f"Trajectory crossed virtual fence line '{zone.name}' on camera {camera_name}."
                            evt_type = "FENCE_JUMP"
                        elif zone.zone_type.lower() == 'restricted area' or 'restricted' in zone.name.lower():
                            inc_type = "Restricted Area Entry"
                            explanation = f"Trajectory entered virtual restricted area zone '{zone.name}' on camera {camera_name}."
                            evt_type = "RESTRICTED_ENTRY"
                        else:
                            inc_type = "Boundary Crossing"
                            explanation = f"Trajectory crossed virtual zone boundary '{zone.name}' on camera {camera_name}."
                            evt_type = "FENCE_JUMP"
                            
                        # Avoid duplicates
                        existing_stmt = (
                            select(Incident)
                            .join(DetectedEvent, Incident.id == DetectedEvent.incident_id)
                            .filter(
                                DetectedEvent.track_id == track.id,
                                Incident.incident_type == inc_type,
                                DetectedEvent.timestamp >= incident_time - timedelta(seconds=2),
                                DetectedEvent.timestamp <= incident_time + timedelta(seconds=2)
                            )
                        )
                        existing_res = await db.execute(existing_stmt)
                        if existing_res.scalars().first():
                            continue

                        # Create Incident record
                        incident_id = uuid.uuid4()
                        incident = Incident(
                            id=incident_id,
                            incident_type=inc_type,
                            timestamp=incident_time,
                            camera_id=camera_id,
                            confidence=0.98,
                            explanation=explanation
                        )
                        db.add(incident)

                        # Create DetectedEvent
                        det_event = DetectedEvent(
                            id=uuid.uuid4(),
                            incident_id=incident_id,
                            event_type=evt_type,
                            camera_id=camera_id,
                            video_id=video_id,
                            timestamp=incident_time,
                            track_id=track.id,
                            confidence=0.98
                        )
                        db.add(det_event)

                        # Resolve involved students
                        rec_stmt = (
                            select(StudentRecognitionEvent)
                            .filter(StudentRecognitionEvent.track_id == track.id)
                            .order_by(StudentRecognitionEvent.similarity_score.desc())
                        )
                        rec_res = await db.execute(rec_stmt)
                        rec_event = rec_res.scalars().first()
                        if rec_event:
                            inc_person = IncidentPerson(
                                id=uuid.uuid4(),
                                incident_id=incident_id,
                                student_id=rec_event.student_id,
                                confidence=rec_event.similarity_score
                            )
                            db.add(inc_person)

                        # Generate Evidence (Screenshot frame and Video clip)
                        reid_stmt = (
                            select(PersonReid)
                            .filter(PersonReid.track_id == track.id)
                            .order_by(PersonReid.timestamp_seconds.asc())
                        )
                        reid_res = await db.execute(reid_stmt)
                        reid_obj = reid_res.scalars().first()
                        screenshot_path = reid_obj.crop_path if reid_obj else video.file_path
                        
                        ev_screen = Evidence(
                            id=uuid.uuid4(),
                            incident_id=incident_id,
                            evidence_type="screenshot",
                            file_path=screenshot_path,
                            timestamp=incident_time
                        )
                        db.add(ev_screen)

                        # Cut H.264 Video Sub-clip
                        clip_filename = f"clip_{incident_id.hex}.mp4"
                        clip_path = os.path.join(settings.STORAGE_DIR, "evidence", clip_filename)
                        clip_success = generate_subclip(video.file_path, t_sec, 6.0, clip_path)
                        
                        if clip_success:
                            ev_video = Evidence(
                                id=uuid.uuid4(),
                                incident_id=incident_id,
                                evidence_type="video",
                                file_path=clip_path,
                                timestamp=incident_time
                            )
                            db.add(ev_video)

                        incidents_created += 1
                        break

        # --- B. SEMANTIC VECTOR CHECK + MULTI-SIGNAL hardeners ---
        try:
            vector_store = QdrantVectorStore()
            embedder = CLIPEmbedder()
            
            # 1. Fight Semantic Checks
            fight_matches = vector_store.search_by_text(
                text_query="people fighting, physical altercation, fight, clash, argument",
                embedder=embedder,
                limit=15,
                video_id=str(video_id)
            )
            
            fight_incidents = []
            for match in fight_matches:
                score = match["score"]
                if score < 0.18:
                    continue
                payload = match["payload"]
                t_sec = float(payload.get("timestamp", 0.0))
                
                # Check duplicate time windows
                too_close = False
                for ft in fight_incidents:
                    if abs(ft - t_sec) < 10.0:
                        too_close = True
                        break
                if too_close:
                    continue
                
                # Compute multi-signal score
                fight_score, breakdown = fight_detector.analyze(tracks, score, t_sec)
                logger.info(f"Fight multi-signal analysis at {t_sec}s: score={fight_score:.3f}, breakdown={breakdown}")
                
                if fight_score < 0.30:
                    logger.info("Fight multi-signal threshold not met. Bypassing event creation.")
                    continue
                    
                fight_incidents.append(t_sec)
                incident_time = video.created_at + timedelta(seconds=t_sec)
                track_id = uuid.UUID(payload["track_id"]) if "track_id" in payload else None
                
                incident_id = uuid.uuid4()
                incident = Incident(
                    id=incident_id,
                    incident_type="Fight",
                    timestamp=incident_time,
                    camera_id=camera_id,
                    confidence=fight_score,
                    explanation=(
                        f"Detected physical fight/altercation at {t_sec:.1f}s on camera {camera_name}. "
                        f"Multi-signal breakdown: Motion dynamics: {breakdown['motion_dynamics']:.2f}, "
                        f"Interaction proximity: {breakdown['person_interaction']:.2f}, CLIP score: {breakdown['clip_similarity']:.2f}."
                    )
                )
                db.add(incident)

                # Create DetectedEvent
                det_event = DetectedEvent(
                    id=uuid.uuid4(),
                    incident_id=incident_id,
                    event_type="FIGHT",
                    camera_id=camera_id,
                    video_id=video_id,
                    timestamp=incident_time,
                    track_id=track_id,
                    confidence=fight_score
                )
                db.add(det_event)

                # Resolve all involved students for tracks in this video around timestamp
                for trk in tracks:
                    rec_stmt = (
                        select(StudentRecognitionEvent)
                        .filter(StudentRecognitionEvent.track_id == trk.id)
                        .order_by(StudentRecognitionEvent.similarity_score.desc())
                    )
                    rec_res = await db.execute(rec_stmt)
                    rec_event = rec_res.scalars().first()
                    if rec_event:
                        # Ensure duplicate student not added
                        existing_ip = await db.execute(
                            select(IncidentPerson).filter(
                                IncidentPerson.incident_id == incident_id,
                                IncidentPerson.student_id == rec_event.student_id
                            )
                        )
                        if not existing_ip.scalars().first():
                            inc_person = IncidentPerson(
                                id=uuid.uuid4(),
                                incident_id=incident_id,
                                student_id=rec_event.student_id,
                                confidence=rec_event.similarity_score
                            )
                            db.add(inc_person)

                # Generate Evidence
                screenshot_path = payload.get("crop_path", video.file_path)
                ev_screen = Evidence(
                    id=uuid.uuid4(),
                    incident_id=incident_id,
                    evidence_type="screenshot",
                    file_path=screenshot_path,
                    timestamp=incident_time
                )
                db.add(ev_screen)

                # Cut H.264 Video Sub-clip
                clip_filename = f"clip_{incident_id.hex}.mp4"
                clip_path = os.path.join(settings.STORAGE_DIR, "evidence", clip_filename)
                clip_success = generate_subclip(video.file_path, t_sec, 6.0, clip_path)
                if clip_success:
                    ev_video = Evidence(
                        id=uuid.uuid4(),
                        incident_id=incident_id,
                        evidence_type="video",
                        file_path=clip_path,
                        timestamp=incident_time
                    )
                    db.add(ev_video)

                incidents_created += 1

            # 2. Suspicious Activity Semantic Checks
            susp_matches = vector_store.search_by_text(
                text_query="person running quickly, suspicious activity, vandalising, hiding",
                embedder=embedder,
                limit=15,
                video_id=str(video_id)
            )

            susp_incidents = []
            for match in susp_matches:
                score = match["score"]
                if score < 0.40:
                    continue
                payload = match["payload"]
                t_sec = float(payload.get("timestamp", 0.0))
                
                # Check duplicate time windows
                too_close = False
                for st in susp_incidents:
                    if abs(st - t_sec) < 10.0:
                        too_close = True
                        break
                if too_close:
                    continue
                
                track_id = uuid.UUID(payload["track_id"]) if "track_id" in payload else None
                track_obj = next((tr for tr in tracks if tr.id == track_id), None)
                
                if track_obj:
                    susp_score, breakdown = suspicious_detector.analyze(track_obj, score)
                else:
                    susp_score = score
                    breakdown = {"clip_similarity": score, "motion_dynamics": 0.0}

                if susp_score < 0.45:
                    continue
                    
                susp_incidents.append(t_sec)
                incident_time = video.created_at + timedelta(seconds=t_sec)
                
                incident_id = uuid.uuid4()
                incident = Incident(
                    id=incident_id,
                    incident_type="Suspicious Activity",
                    timestamp=incident_time,
                    camera_id=camera_id,
                    confidence=susp_score,
                    explanation=(
                        f"Flagged suspicious activity pattern at {t_sec:.1f}s on camera {camera_name}. "
                        f"Speed score: {breakdown.get('motion_dynamics', 0.0):.2f}, CLIP match: {breakdown.get('clip_similarity', 0.0):.2f}."
                    )
                )
                db.add(incident)

                # Create DetectedEvent
                det_event = DetectedEvent(
                    id=uuid.uuid4(),
                    incident_id=incident_id,
                    event_type="SUSPICIOUS",
                    camera_id=camera_id,
                    video_id=video_id,
                    timestamp=incident_time,
                    track_id=track_id,
                    confidence=susp_score
                )
                db.add(det_event)

                # Resolve involved students
                if track_id:
                    rec_stmt = (
                        select(StudentRecognitionEvent)
                        .filter(StudentRecognitionEvent.track_id == track_id)
                        .order_by(StudentRecognitionEvent.similarity_score.desc())
                    )
                    rec_res = await db.execute(rec_stmt)
                    rec_event = rec_res.scalars().first()
                    if rec_event:
                        inc_person = IncidentPerson(
                            id=uuid.uuid4(),
                            incident_id=incident_id,
                            student_id=rec_event.student_id,
                            confidence=rec_event.similarity_score
                        )
                        db.add(inc_person)

                # Generate Evidence
                screenshot_path = payload.get("crop_path", video.file_path)
                ev_screen = Evidence(
                    id=uuid.uuid4(),
                    incident_id=incident_id,
                    evidence_type="screenshot",
                    file_path=screenshot_path,
                    timestamp=incident_time
                )
                db.add(ev_screen)

                # Cut H.264 Video Sub-clip
                clip_filename = f"clip_{incident_id.hex}.mp4"
                clip_path = os.path.join(settings.STORAGE_DIR, "evidence", clip_filename)
                clip_success = generate_subclip(video.file_path, t_sec, 6.0, clip_path)
                if clip_success:
                    ev_video = Evidence(
                        id=uuid.uuid4(),
                        incident_id=incident_id,
                        evidence_type="video",
                        file_path=clip_path,
                        timestamp=incident_time
                    )
                    db.add(ev_video)

                incidents_created += 1

        except Exception as qe:
            logger.warning(f"Qdrant/CLIP incident semantic parsing failed or bypassed: {str(qe)}")

        await db.commit()
        logger.info(f"Incident detection engine execution completed. Created {incidents_created} incidents.")
        return incidents_created
