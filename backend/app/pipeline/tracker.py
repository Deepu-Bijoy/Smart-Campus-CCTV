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
        use_half = getattr(detector, "half", False) and str(getattr(detector, "device", "")).startswith("cuda")
        track_kwargs = {
            "persist": persist,
            "tracker": tracker_cfg,
            "conf": 0.25,
            "classes": detector.target_classes,
            "device": detector.device,
            "verbose": False
        }
        if use_half:
            track_kwargs["half"] = True

        try:
            results = detector.model.track(frame, **track_kwargs)
        except Exception as te:
            logger.warning(f"Tracker with {tracker_cfg} failed ({te}). Falling back to default bytetrack.yaml")
            track_kwargs["tracker"] = "bytetrack.yaml"
            results = detector.model.track(frame, **track_kwargs)
        return results[0] if results else None
