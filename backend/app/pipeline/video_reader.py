import cv2
import logging
from typing import Generator, Tuple, Any, Optional

logger = logging.getLogger(__name__)

class VideoReader:
    def __init__(self, file_path: str, target_fps: float = 5.0):
        self.file_path = file_path
        self.target_fps = target_fps

    def read_frames(
        self,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> Generator[Tuple[int, float, Any], None, None]:
        """
        Reads frames from the video file sequentially at target_fps.
        Optionally accepts start_time and end_time (in seconds) to process
        only a specific segment window.
        Uses cap.grab() to skip decoding non-target frames for high performance.
        Yields: (frame_number, timestamp_seconds, frame_image)
        """
        cap = cv2.VideoCapture(self.file_path)
        if not cap.isOpened():
            logger.error(f"Cannot open video file: {self.file_path}")
            return
            
        original_fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        if original_fps <= 0:
            logger.error(f"Invalid original FPS: {original_fps}")
            cap.release()
            return
            
        frame_interval = max(1, round(original_fps / self.target_fps))
        
        logger.info(
            f"Processing video: {self.file_path}. Original FPS: {original_fps:.2f}, "
            f"Target FPS: {self.target_fps}, Frame Interval: {frame_interval}, "
            f"Window: [{start_time if start_time is not None else 0.0}s, {end_time if end_time is not None else 'EOF'}s]"
        )
        
        frame_num = 0
        if start_time is not None and start_time > 0:
            target_start_frame = int(round(start_time * original_fps))
            if 0 <= target_start_frame < total_frames:
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_start_frame)
                frame_num = target_start_frame
        
        end_frame = int(round(end_time * original_fps)) if (end_time is not None and end_time > 0) else None
        yielded_count = 0
        
        try:
            while True:
                if end_frame is not None and frame_num > end_frame:
                    break
                    
                if frame_num % frame_interval == 0:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    timestamp = frame_num / original_fps
                    if end_time is not None and timestamp > (end_time + 1e-3):
                        break
                    yield frame_num, timestamp, frame
                    yielded_count += 1
                else:
                    ret = cap.grab()
                    if not ret:
                        break
                frame_num += 1
        finally:
            cap.release()
            logger.info(f"Finished reading video. Total frames processed: {yielded_count}/{frame_num}")
