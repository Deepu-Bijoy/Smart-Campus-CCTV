import cv2
import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def extract_video_metadata(file_path: str) -> Dict[str, Any]:
    """
    Extracts metadata from a video file using OpenCV.
    Returns a dictionary containing: duration, fps, width, height, codec, and file_size.
    """
    metadata = {
        "duration": 0.0,
        "fps": 0.0,
        "width": 0,
        "height": 0,
        "codec": "unknown",
        "file_size": 0
    }
    
    if not os.path.exists(file_path):
        logger.error(f"Video file not found at: {file_path}")
        return metadata
        
    try:
        metadata["file_size"] = os.path.getsize(file_path)
        
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            logger.error(f"OpenCV could not open video file: {file_path}")
            return metadata
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        # Decode FourCC integer to string representation
        fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
        codec = "".join([chr((fourcc_int >> 8 * i) & 0xFF) for i in range(4)])
        codec = codec.strip().replace('\x00', '')
        if not codec:
            codec = "unknown"
            
        duration = 0.0
        if fps > 0:
            duration = frame_count / fps
            
        cap.release()
        
        metadata.update({
            "duration": float(duration),
            "fps": float(fps),
            "width": width,
            "height": height,
            "codec": codec
        })
        
        logger.info(f"Successfully extracted video metadata for {file_path}: {metadata}")
    except Exception as e:
        logger.error(f"Error extracting video metadata for {file_path}: {str(e)}")
        
    return metadata
