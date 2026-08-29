import cv2
import logging
from typing import Generator, Tuple, Any

logger = logging.getLogger(__name__)

class VideoReader:
    def __init__(self, file_path: str, target_fps: float = 5.0):
        self.file_path = file_path
        self.target_fps = target_fps

    def read_frames(self) -> Generator[Tuple[int, float, Any], None, None]:
        """
        Reads frames from the video file sequentially at target_fps.
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
            f"Target FPS: {self.target_fps}, Frame Interval: {frame_interval}"
        )
        
        frame_num = 0
        yielded_count = 0
        
        try:
            while True:
                if frame_num % frame_interval == 0:
                    ret, frame = cap.read()
                    if not ret:
                        break
                    timestamp = frame_num / original_fps
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
