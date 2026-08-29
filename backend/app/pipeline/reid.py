import torch
import logging
import numpy as np
from typing import List
from app.core.model_manager import model_manager
import torch.nn.functional as F

logger = logging.getLogger(__name__)

class OSNetReIDExtractor:
    def __init__(self, model_name: str = "osnet_x1_0"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Retrieving torchreid FeatureExtractor ({model_name}) from Model Manager")
        self.extractor = model_manager.get_osnet(model_name)

    def extract_batch(self, crop_images: List[np.ndarray]) -> List[List[float]]:
        """
        Extracts L2-normalized 512-dimensional Re-ID embeddings for a batch of crop images (RGB).
        """
        if not crop_images:
            return []
            
        try:
            with torch.no_grad():
                features = self.extractor(crop_images)
                normalized_features = F.normalize(features, p=2, dim=1)
                return normalized_features.cpu().numpy().tolist()
        except Exception as e:
            logger.error(f"Error extracting Re-ID batch: {str(e)}")
            return []
