import os
import uuid
import cv2
import torch
import logging
from typing import List, Dict, Any, Tuple
from app.core.config import settings
from app.pipeline.video_reader import VideoReader
from app.pipeline.detector import YOLOv8Detector
from app.pipeline.tracker import ByteTrackTracker
from app.pipeline.reid import OSNetReIDExtractor
from app.pipeline.embedder import CLIPEmbedder

logger = logging.getLogger(__name__)

class FrameProcessor:
    def __init__(self, video_id: uuid.UUID, file_path: str, target_fps: float = 5.0, camera_id: str = "cam_1"):
        self.video_id = video_id
        self.camera_id = camera_id
        self.reader = VideoReader(file_path, target_fps=target_fps)
        self.detector = YOLOv8Detector()
        self.tracker = ByteTrackTracker()
        self.reid_extractor = OSNetReIDExtractor()
        self.clip_embedder = CLIPEmbedder()
        
        self.crops_dir = os.path.join(settings.STORAGE_DIR, "crops", str(video_id))
        os.makedirs(self.crops_dir, exist_ok=True)

    def process(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]], int]:
        """
        Processes video frames, detects objects, runs tracking, and extracts Re-ID & CLIP embeddings.
        Returns: (tracks_list, detections_list, reids_list, clips_list, processed_count)
        """
        tracks_map = {}
        detections_list = []
        crops_queue = []
        reids_list = []
        clips_list = []
        track_last_crop_frame = {}
        
        logger.info(f"Frame extraction, tracking, and embeddings started for video {self.video_id} (Camera: {self.camera_id}).")
        frame_generator = self.reader.read_frames()
        processed_count = 0
        
        for frame_num, timestamp, frame in frame_generator:
            persist = processed_count > 0
            result = self.tracker.track_frame(self.detector, frame, persist=persist)
            processed_count += 1
            
            if result is None or result.boxes is None:
                continue
                
            boxes = result.boxes
            
            if boxes.id is not None:
                tracker_ids = boxes.id.int().cpu().tolist()
                xyxys = boxes.xyxy.cpu().tolist()
                confs = boxes.conf.cpu().tolist()
                clss = boxes.cls.int().cpu().tolist()
                
                height, width = frame.shape[:2]
                
                for xyxy, track_id, conf, cls_id in zip(xyxys, tracker_ids, confs, clss):
                    object_class = self.detector.class_names.get(cls_id, "unknown")
                    
                    if track_id not in tracks_map:
                        tracks_map[track_id] = {
                            "tracker_id": track_id,
                            "object_class": object_class,
                            "start_time": timestamp,
                            "end_time": timestamp,
                        }
                    else:
                        tracks_map[track_id]["end_time"] = timestamp
                        
                    detection_data = {
                        "frame_number": frame_num,
                        "timestamp_seconds": timestamp,
                        "bounding_box": xyxy,
                        "confidence": conf,
                        "track_temp_id": track_id,
                        "object_class": object_class
                    }
                    
                    detections_list.append(detection_data)
                    
                    # Task 2: Validation threshold >= 0.3 and track representative crop sampling (every 3 frames)
                    if conf >= 0.3:
                        last_frame = track_last_crop_frame.get(track_id, -10)
                        if frame_num - last_frame >= 3 or last_frame < 0:
                            x1, y1, x2, y2 = xyxy
                            x1_abs = max(0, int(round(x1)))
                            y1_abs = max(0, int(round(y1)))
                            x2_abs = min(width, int(round(x2)))
                            y2_abs = min(height, int(round(y2)))
                            
                            crop_w = x2_abs - x1_abs
                            crop_h = y2_abs - y1_abs
                            
                            # Validate crop size
                            min_w = 20
                            min_h = 40 if object_class == "person" else 20
                            
                            if crop_w >= min_w and crop_h >= min_h:
                                crop = frame[y1_abs:y2_abs, x1_abs:x2_abs]
                                if crop.size > 0:
                                    crop_filename = f"{track_id}_{frame_num}_{uuid.uuid4().hex[:6]}.jpg"
                                    crop_path = os.path.join(self.crops_dir, crop_filename)
                                    try:
                                        cv2.imwrite(crop_path, crop)
                                        crops_queue.append({
                                            "track_temp_id": track_id,
                                            "timestamp_seconds": timestamp,
                                            "crop_path": crop_path,
                                            "object_class": object_class,
                                            "confidence": conf,
                                            "bounding_box": [float(x1), float(y1), float(x2), float(y2)],
                                            "camera_id": self.camera_id
                                        })
                                        track_last_crop_frame[track_id] = frame_num
                                    except Exception as e:
                                        logger.error(f"Failed to write crop image: {str(e)}")
            
            if processed_count % 50 == 0:
                logger.info(f"Processed {processed_count} frames. Queued crops for embeddings: {len(crops_queue)}")

        if crops_queue:
            logger.info(f"Extracting CLIP embeddings in batches of 64 for {len(crops_queue)} crops.")
            batch_size = 64
            for i in range(0, len(crops_queue), batch_size):
                chunk = crops_queue[i : i + batch_size]
                imgs = []
                valid_chunk = []
                for item in chunk:
                    img = cv2.imread(item["crop_path"])
                    if img is not None:
                        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        imgs.append(img_rgb)
                        valid_chunk.append(item)
                
                if imgs:
                    clip_embeddings = self.clip_embedder.get_image_embeddings(imgs)
                    for item, emb in zip(valid_chunk, clip_embeddings):
                        clips_list.append({
                            "track_temp_id": item["track_temp_id"],
                            "embedding": emb,
                            "timestamp_seconds": item["timestamp_seconds"],
                            "crop_path": item["crop_path"],
                            "object_class": item["object_class"],
                            "confidence": item["confidence"],
                            "bounding_box": item["bounding_box"],
                            "camera_id": item["camera_id"]
                        })

        person_crops = [item for item in crops_queue if item["object_class"] == "person"]
        if person_crops:
            logger.info(f"Extracting OSNet Re-ID embeddings for {len(person_crops)} people crops.")
            batch_size = 64
            for i in range(0, len(person_crops), batch_size):
                chunk = person_crops[i : i + batch_size]
                imgs = []
                valid_chunk = []
                for item in chunk:
                    img = cv2.imread(item["crop_path"])
                    if img is not None:
                        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
                        imgs.append(img_rgb)
                        valid_chunk.append(item)
                
                if imgs:
                    reid_embeddings = self.reid_extractor.extract_batch(imgs)
                    for item, emb in zip(valid_chunk, reid_embeddings):
                        reids_list.append({
                            "track_temp_id": item["track_temp_id"],
                            "embedding": emb,
                            "timestamp_seconds": item["timestamp_seconds"],
                            "crop_path": item["crop_path"],
                            "camera_id": item["camera_id"],
                            "confidence": item["confidence"],
                            "bounding_box": item["bounding_box"]
                        })

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            
        final_tracks = []
        for track_id, t_data in tracks_map.items():
            final_tracks.append({
                "tracker_id": t_data["tracker_id"],
                "object_class": t_data["object_class"],
                "start_time": t_data["start_time"],
                "end_time": t_data["end_time"],
                "temp_id": track_id
            })
            
        # Stage 1-5 print instrumentation
        person_count = len([d for d in detections_list if d.get("object_class") == "person"])
        print(f"Stage 1: Number of detected persons: {person_count}")
        print(f"Stage 2: Number of tracks: {len(tracks_map)}")
        print(f"Stage 3: Number of crops extracted: {len(crops_queue)}")
        print(f"Stage 4: Number of CLIP embeddings generated: {len(clips_list)}")
        for idx, c in enumerate(clips_list):
            print(f"Stage 5: Embedding {idx} length: {len(c['embedding'])}")
            
        return final_tracks, detections_list, reids_list, clips_list, processed_count
