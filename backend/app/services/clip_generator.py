import os
import logging
import subprocess
import cv2

logger = logging.getLogger(__name__)

def is_ffmpeg_available() -> bool:
    """Checks if FFmpeg is installed and accessible in the system path."""
    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        res = subprocess.run(
            ["ffmpeg", "-version"], 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
            check=False
        )
        return res.returncode == 0
    except Exception:
        return False

def generate_subclip(video_path: str, timestamp: float, duration: float, output_path: str) -> bool:
    """
    Generates a browser-compatible H.264 sub-clip centered at the target timestamp.
    Prioritizes FFmpeg with libx264 and aac encoding, falling back to OpenCV VideoWriter if unavailable.
    """
    if not os.path.exists(video_path):
        logger.error(f"Source video file not found at: {video_path}")
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    # Calculate start and duration
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Failed to open source video at: {video_path}")
        return False

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_len = total_frames / fps if total_frames > 0 else 0.0
    cap.release()

    if video_len > 0:
        # Event near beginning: start at 0.0
        # Event near end: shift start back to capture up to full duration
        if (timestamp + (duration / 2.0)) > video_len:
            start_sec = max(0.0, video_len - duration)
        else:
            start_sec = max(0.0, timestamp - (duration / 2.0))
        actual_duration = max(0.5, min(duration, video_len - start_sec))
    else:
        start_sec = max(0.0, timestamp - (duration / 2.0))
        actual_duration = duration

    # 1. FFmpeg Encoding Strategy
    if is_ffmpeg_available():
        logger.info("FFmpeg detected. Executing H.264 transcoding pipeline...")
        try:
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start_sec:.3f}",
                "-i", video_path,
                "-t", f"{actual_duration:.3f}",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-movflags", "+faststart",
                output_path
            ]
            
            res = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                text=True,
                check=False
            )
            
            if res.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Sub-clip generated successfully using FFmpeg: {output_path}")
                return True
            else:
                logger.warning(f"FFmpeg slicing failed (code {res.returncode}). Error details:\n{res.stderr}")
        except Exception as fe:
            logger.error(f"Failed to execute FFmpeg command: {str(fe)}")

    # 2. OpenCV Fallback Strategy (MPEG-4 mp4v codec)
    logger.warning("FFmpeg unavailable or failed. Falling back to OpenCV only mp4v encoder.")
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    start_frame = int(start_sec * fps)
    end_frame = int((start_sec + actual_duration) * fps)

    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    if not out.isOpened():
        cap.release()
        return False

    frames_written = 0
    current_frame = start_frame
    while current_frame <= end_frame:
        ret, frame = cap.read()
        if not ret:
            break
        out.write(frame)
        frames_written += 1
        current_frame += 1

    cap.release()
    out.release()
    
    if frames_written > 0:
        logger.info(f"Sub-clip generated successfully using OpenCV fallback: {output_path}")
        return True
    else:
        if os.path.exists(output_path):
            os.remove(output_path)
        return False

def extract_evidence_frame(video_path: str, timestamp: float, output_path: str) -> bool:
    """
    Extracts a representative full-frame image (JPEG) from the video at the given timestamp.
    Handles boundaries gracefully (start, end, beyond length) and returns False on failure.
    """
    if not os.path.exists(video_path):
        logger.error(f"Source video file not found at: {video_path}")
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Failed to open source video at: {video_path}")
        return False

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 25.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total_frames <= 0:
            logger.warning(f"Video has 0 or invalid frame count: {video_path}")
            cap.release()
            return False

        # Target frame calculation bounded between 0 and total_frames - 1
        target_frame = max(0, min(int(timestamp * fps), total_frames - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
        ret, frame = cap.read()

        if not ret or frame is None or frame.size == 0:
            # Fallback to reading first available frame
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = cap.read()

        cap.release()

        if ret and frame is not None and frame.size > 0:
            success = cv2.imwrite(output_path, frame)
            if success and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                logger.info(f"Evidence frame extracted successfully: {output_path}")
                return True
            else:
                logger.warning(f"Failed to write evidence frame image to: {output_path}")
                return False
        return False
    except Exception as e:
        logger.error(f"Exception while extracting evidence frame: {str(e)}")
        if cap.isOpened():
            cap.release()
        return False

