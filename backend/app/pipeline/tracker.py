import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

CUSTOM_TRACKER_CONFIG = os.path.join(os.path.dirname(__file__), "bytetrack_custom.yaml")

class ByteTrackTracker:
    def __init__(self):
        logger.info(f"Initializing ByteTrack Tracker wrapper with config: {CUSTOM_TRACKER_CONFIG}")

    def track_frame(self, detector: Any, frame: Any, persist: bool = True) -> Any:
        """
        Tracks objects in a single frame using ByteTrack. Maintains IDs over time.
        """
        tracker_cfg = CUSTOM_TRACKER_CONFIG if os.path.exists(CUSTOM_TRACKER_CONFIG) else "bytetrack.yaml"
        results = detector.model.track(
            frame,
            persist=persist,
            tracker=tracker_cfg,
            conf=0.25,
            classes=detector.target_classes,
            device=detector.device,
            verbose=False
        )
        return results[0] if results else None
