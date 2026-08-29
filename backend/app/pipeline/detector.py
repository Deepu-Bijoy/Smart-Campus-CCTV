try:
    import torch
except ImportError:
    torch = None
from app.core.model_manager import model_manager
import logging
from typing import List, Any

logger = logging.getLogger(__name__)

class YOLOv8Detector:
    def __init__(self, model_name: str = "yolov8n.pt"):
        self.device = ("cuda" if (torch and torch.cuda.is_available()) else "cpu")
        self.half = self.device == "cuda"
        
        logger.info(f"Retrieving YOLOv8 model ({model_name}) from Model Manager")
        self.model = model_manager.get_yolo(model_name)
        
        # Target classes mapping:
        self.target_classes = [0, 1, 2, 3, 5, 7, 24, 26, 28, 63, 67]
        self.class_names = {
            0: "person", 1: "bicycle", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck",
            24: "backpack", 26: "handbag", 28: "suitcase", 63: "laptop", 67: "cell phone"
        }

    def detect_batch(self, frames: List[Any]) -> List[Any]:
        """
        Runs batch inference on a list of frames.
        """
        results = self.model(
            frames,
            device=self.device,
            classes=self.target_classes,
            verbose=False
        )
        return results
