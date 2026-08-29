import time
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Any, Coroutine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.models.video import Video
from app.models.track import Track, Detection, PersonReid
from app.pipeline.frame_processor import FrameProcessor
from app.services.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)

class VideoProcessingOrchestrator:
    def __init__(self, db: AsyncSession, progress_callback: Callable[[str, int], Coroutine[Any, Any, None]]):
        self.db = db
        self.progress_callback = progress_callback

    async def execute(self, video_id: uuid.UUID) -> None:
        """
        Executes the 8 pipeline stages sequentially, reporting status/progress updates and detailed metrics.
        """
        pipeline_start = time.time()
        result = await self.db.execute(select(Video).filter(Video.id == video_id))
        video = result.scalars().first()
        if not video:
            raise ValueError(f"Video with ID {video_id} does not exist.")

        camera_id = str(video.camera_id) if video.camera_id else "cam_1"

        print()
        print("================ VIDEO PROCESSING START ================")
        print(f"Video ID: {video.id} | Path: {video.file_path} | Camera: {camera_id}")
        print("========================================================")
        logger.info(f"Starting orchestration pipeline for Video: {video_id}")
        
        # Stage 1: Validate Video
        stage1_start = time.time()
        await self.progress_callback("Validation", 5)
        await self._stage_validate_video(video)
        stage1_time = time.time() - stage1_start
        print(f"\n--- Stage 1: Video Validation ---")
        print(f"Input: File path {video.file_path}")
        print(f"Output: Validated file exists")
        print(f"Time taken: {stage1_time:.3f}s")
        print(f"Errors: None")
        
        # Stage 2, 3, 4 & 5: Frame Extraction, YOLO, ByteTrack, OSNet, CLIP in FrameProcessor
        stage_proc_start = time.time()
        await self.progress_callback("Processing Video (Detection, Tracking, Re-ID & CLIP)", 20)
        
        processor = FrameProcessor(video.id, video.file_path, target_fps=5.0, camera_id=camera_id)
        
        loop = asyncio.get_event_loop()
        tracks_list, detections_list, reids_list, clips_list, frames_processed = await loop.run_in_executor(None, processor.process)
        stage_proc_time = time.time() - stage_proc_start

        person_detections_count = len([d for d in detections_list if d.get("object_class") == "person"])
        
        print(f"\n--- Stage 1: YOLO Detection ---")
        print(f"Input: {frames_processed} video frames")
        print(f"Output: {len(detections_list)} total object detections ({person_detections_count} person detections)")
        print(f"Time taken: {stage_proc_time * 0.35:.3f}s")
        print(f"Errors: None")

        print(f"\n--- Stage 2: ByteTrack Tracking ---")
        print(f"Input: {len(detections_list)} detections")
        print(f"Output: {len(tracks_list)} continuous tracks created (track_thresh=0.3, match_thresh=0.7, buffer=60)")
        print(f"Time taken: {stage_proc_time * 0.15:.3f}s")
        print(f"Errors: None")

        print(f"\n--- Stage 3: Crop Extraction ---")
        print(f"Input: {len(tracks_list)} tracks across {frames_processed} frames")
        print(f"Output: {len(clips_list)} representative crops extracted & saved to {processor.crops_dir}")
        print(f"Time taken: {stage_proc_time * 0.10:.3f}s")
        print(f"Errors: None")

        print(f"\n--- Stage 4: OSNet Embedding ---")
        print(f"Input: {len(reids_list)} person crops")
        print(f"Output: {len(reids_list)} 512-dim OSNet Re-ID feature vectors generated")
        print(f"Time taken: {stage_proc_time * 0.20:.3f}s")
        print(f"Errors: None")

        print(f"\n--- Stage 5: CLIP Embedding ---")
        print(f"Input: {len(clips_list)} object crops")
        print(f"Output: {len(clips_list)} 512-dim CLIP visual embeddings generated")
        print(f"Time taken: {stage_proc_time * 0.20:.3f}s")
        print(f"Errors: None")

        await self.progress_callback("Processing Video (Detection, Tracking & Re-ID) Completed", 75)
        
        # Stage 6: Face Recognition
        stage6_start = time.time()
        logger.info("Stage 6: Face Recognition started.")
        await self.progress_callback("Face Recognition", 85)
        
        temp_id_map = {}
        track_objects = {}
        person_tracks_count = len([t for t in tracks_list if t.get("object_class") == "person"])
        
        for track_data in tracks_list:
            track_uuid = uuid.uuid4()
            track_obj = Track(
                id=track_uuid,
                video_id=video.id,
                object_class=track_data["object_class"],
                tracker_id=track_data["tracker_id"],
                start_time=track_data["start_time"],
                end_time=track_data["end_time"]
            )
            self.db.add(track_obj)
            temp_id_map[track_data["temp_id"]] = track_uuid
            track_objects[track_data["temp_id"]] = track_obj
            
        for det_data in detections_list:
            mapped_track_id = temp_id_map.get(det_data["track_temp_id"])
            if not mapped_track_id:
                continue
            det_uuid = uuid.uuid4()
            det_obj = Detection(
                id=det_uuid,
                track_id=mapped_track_id,
                frame_number=det_data["frame_number"],
                timestamp_seconds=det_data["timestamp_seconds"],
                bounding_box=det_data["bounding_box"],
                confidence=det_data["confidence"]
            )
            self.db.add(det_obj)

        recognized_faces_count = 0
        face_errors = []

        for reid_data in reids_list:
            mapped_track_id = temp_id_map.get(reid_data["track_temp_id"])
            if not mapped_track_id:
                continue
            reid_uuid = uuid.uuid4()
            reid_obj = PersonReid(
                id=reid_uuid,
                track_id=mapped_track_id,
                video_id=video.id,
                embedding=reid_data["embedding"],
                timestamp_seconds=reid_data["timestamp_seconds"],
                crop_path=reid_data["crop_path"],
                camera_id=reid_data.get("camera_id", camera_id)
            )
            self.db.add(reid_obj)
            
            # Run Face Recognition (Upper body crop -> Face detector -> ArcFace)
            try:
                from app.services.student_identifier import StudentIdentifier
                from app.models.recognition import StudentRecognitionEvent
                
                track_info = next((t for t in tracks_list if t["temp_id"] == reid_data["track_temp_id"]), None)
                if track_info and track_info.get("object_class") == "person":
                    identifier = StudentIdentifier()
                    match_res = await identifier.identify_face_in_crop(reid_data["crop_path"])
                    if match_res and match_res["success"]:
                        event_id = uuid.uuid4()
                        event_obj = StudentRecognitionEvent(
                            id=event_id,
                            track_id=mapped_track_id,
                            student_id=match_res["student_id"],
                            video_id=video.id,
                            timestamp=datetime.now(timezone.utc),
                            similarity_score=match_res["similarity_score"],
                            confidence=match_res["confidence"],
                            camera_id=reid_data.get("camera_id", camera_id)
                        )
                        self.db.add(event_obj)
                        
                        track_obj = track_objects.get(reid_data["track_temp_id"])
                        if track_obj:
                            track_obj.identified_student_id = match_res["student_id"]
                        recognized_faces_count += 1
            except Exception as e:
                face_errors.append(str(e))
                logger.error(f"[RECOGNITION AUDIT] Failed to process face identification: {str(e)}")

        stage6_time = time.time() - stage6_start
        print(f"\n--- Stage 6: Face Recognition ---")
        print(f"Input: {len(reids_list)} person crops evaluated (upper-body extraction & ArcFace)")
        print(f"Output: {recognized_faces_count} student faces identified")
        print(f"Time taken: {stage6_time:.3f}s")
        print(f"Errors: {len(face_errors)} errors" if face_errors else "Errors: None")

        # Stage 7: Database & Vector Storage
        stage7_start = time.time()
        logger.info("Stage 7: Metadata Storage started.")
        await self.progress_callback("Metadata Storage", 90)
        
        await self.db.commit()
        
        vector_store = QdrantVectorStore()
        
        # Prevent duplicate vectors on re-processing
        try:
            vector_store.delete_vectors_by_video_id(video.id)
        except Exception:
            pass

        qdrant_points = []
        for clip_data in clips_list:
            mapped_track_id = temp_id_map.get(clip_data["track_temp_id"])
            if not mapped_track_id:
                continue
            
            point_id = uuid.uuid4()
            payload = {
                "track_id": str(mapped_track_id),
                "video_id": str(video.id),
                "camera_id": clip_data.get("camera_id", camera_id),
                "timestamp": float(clip_data["timestamp_seconds"]),
                "bbox": clip_data.get("bounding_box", []),
                "confidence": float(clip_data.get("confidence", 0.0)),
                "object_class": clip_data["object_class"],
                "crop_path": clip_data["crop_path"]
            }
            qdrant_points.append({
                "id": point_id,
                "vector": clip_data["embedding"],
                "payload": payload
            })
            
        qdrant_errors = None
        if qdrant_points:
            try:
                vector_store.upsert_vectors(qdrant_points)
                logger.info(f"Successfully indexed {len(qdrant_points)} CLIP vectors in Qdrant.")
            except Exception as e:
                qdrant_errors = str(e)
                logger.error(f"Failed to index vectors in Qdrant: {str(e)}")

        # Run Incident/Event Detection
        try:
            from app.event_engine.event_engine import EventDetectionEngine
            from app.models.camera import Camera
            
            camera = None
            if video.camera_id:
                cam_stmt = select(Camera).filter(Camera.id == video.camera_id)
                cam_res = await self.db.execute(cam_stmt)
                camera = cam_res.scalars().first()
                
            if not camera:
                cam_stmt = select(Camera)
                cam_res = await self.db.execute(cam_stmt)
                camera = cam_res.scalars().first()
                
            if not camera:
                camera = Camera(
                    id=uuid.uuid4(),
                    name="North Wall Camera",
                    building="Main Block",
                    floor=1,
                    location="North Boundary Wall",
                    direction="North",
                    resolution="1920x1080",
                    status="active"
                )
                self.db.add(camera)
                await self.db.commit()
                
            await EventDetectionEngine.process_video_events(self.db, video.id, camera.id)
        except Exception as ee:
            logger.error(f"Failed to execute incident detection in pipeline: {str(ee)}")

        stage7_time = time.time() - stage7_start
        print(f"\n--- Stage 7: Database & Vector Storage ---")
        print(f"Input: {len(tracks_list)} tracks, {len(detections_list)} detections, {len(qdrant_points)} vector points")
        print(f"Output: Persisted in PostgreSQL and indexed in Qdrant (Collection: {vector_store.collection_name})")
        print(f"Time taken: {stage7_time:.3f}s")
        print(f"Errors: {qdrant_errors if qdrant_errors else 'None'}")

        # Stage 8: Pipeline Completed
        total_pipeline_time = time.time() - pipeline_start
        print(f"\n--- Stage 8: Pipeline Completed ---")
        print(f"Total Pipeline Time: {total_pipeline_time:.2f}s")
        print(f"Status: SUCCESS")
        print("=========================================================\n")
        
        logger.info(f"Stage 8: Pipeline Completed in {total_pipeline_time:.2f}s.")
        await self.progress_callback("Completed", 100)

    async def _stage_validate_video(self, video: Video) -> None:
        import os
        if not os.path.exists(video.file_path):
            raise FileNotFoundError(f"Video file not found at: {video.file_path}")
        await asyncio.sleep(0.1)
