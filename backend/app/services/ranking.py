import logging
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class HybridRanker:
    def __init__(self):
        # Default weights
        self.default_weights = {
            "semantic": 0.4,
            "identity": 0.2,
            "appearance": 0.2,
            "temporal": 0.1,
            "zone": 0.05,
            "metadata": 0.05
        }

    def determine_weights(self, intent: str, object_class: str) -> Dict[str, float]:
        """
        Adaptively adjusts weights based on parsed query intent and object class.
        """
        weights = self.default_weights.copy()
        
        # If object is not a person, Re-ID identity/appearance similarities are not applicable
        if object_class != "person":
            return {
                "semantic": 0.6,
                "identity": 0.0,
                "appearance": 0.0,
                "temporal": 0.2,
                "zone": 0.1,
                "metadata": 0.1
            }
            
        if intent == "appearance":
            weights = {
                "semantic": 0.5,
                "identity": 0.1,
                "appearance": 0.3,
                "temporal": 0.05,
                "zone": 0.025,
                "metadata": 0.025
            }
        elif intent == "identity":
            weights = {
                "semantic": 0.2,
                "identity": 0.4,
                "appearance": 0.2,
                "temporal": 0.1,
                "zone": 0.05,
                "metadata": 0.05
            }
        elif intent == "temporal":
            weights = {
                "semantic": 0.3,
                "identity": 0.1,
                "appearance": 0.1,
                "temporal": 0.4,
                "zone": 0.05,
                "metadata": 0.05
            }
        elif intent == "zone":
            weights = {
                "semantic": 0.2,
                "identity": 0.1,
                "appearance": 0.1,
                "temporal": 0.1,
                "zone": 0.4,
                "metadata": 0.1
            }
            
        logger.info(f"Adaptive weights set: {weights} based on intent='{intent}' and class='{object_class}'")
        return weights

    def calculate_temporal_score(
        self, 
        event_time_offset: float, 
        video_start_time: datetime, 
        constraint: Dict[str, Any]
    ) -> float:
        """
        Calculates a score [0.0 - 1.0] indicating how well the event time matches temporal constraints.
        """
        if not constraint:
            return 1.0
            
        # Calculate absolute time of day for the event
        event_abs_time = video_start_time + timedelta(seconds=event_time_offset)
        seconds_of_day = event_abs_time.hour * 3600 + event_abs_time.minute * 60 + event_abs_time.second
        
        target_seconds = constraint["seconds_of_day"]
        relation = constraint["relation"]
        
        if relation == "after":
            if seconds_of_day >= target_seconds:
                return 1.0
            # Gradual decay for times just before the threshold
            diff_hours = (target_seconds - seconds_of_day) / 3600.0
            return float(np.exp(-diff_hours))
        elif relation == "before":
            if seconds_of_day <= target_seconds:
                return 1.0
            diff_hours = (seconds_of_day - target_seconds) / 3600.0
            return float(np.exp(-diff_hours))
        elif relation in ["at", "around"]:
            # Normal distribution centered at target time
            diff_hours = abs(seconds_of_day - target_seconds) / 3600.0
            return float(np.exp(-0.5 * (diff_hours / 0.5) ** 2)) # 30 min standard dev
            
        return 1.0

    def calculate_metadata_score(
        self, 
        payload: Dict[str, Any], 
        filters: Dict[str, Any]
    ) -> float:
        """
        Calculates match score between Qdrant payload and user-supplied filtering properties.
        """
        if not filters:
            return 1.0
            
        matches = 0
        checks = 0
        
        if "camera_id" in filters and filters["camera_id"]:
            checks += 1
            if payload.get("camera_id") == filters["camera_id"]:
                matches += 1
                
        if "object_class" in filters and filters["object_class"]:
            checks += 1
            if payload.get("object_class") == filters["object_class"]:
                matches += 1
                
        if checks == 0:
            return 1.0
            
        return matches / checks
