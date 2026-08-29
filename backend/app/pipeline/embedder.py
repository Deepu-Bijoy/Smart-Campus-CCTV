import torch
import logging
import numpy as np
from PIL import Image
from typing import List, Union
from transformers import CLIPProcessor, CLIPModel

from app.core.model_manager import model_manager

logger = logging.getLogger(__name__)

class CLIPEmbedder:
    def __init__(self, model_name: str = "openai/clip-vit-base-patch32"):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        
        logger.info(f"Retrieving CLIP model ({model_name}) from Model Manager")
        self.model, self.processor = model_manager.get_clip(model_name)

    def get_image_embeddings(self, images: List[Union[Image.Image, np.ndarray]]) -> List[List[float]]:
        """
        Generates normalized 512-dimensional visual embeddings for a batch of images.
        """
        if not images:
            return []
            
        pil_images = []
        for img in images:
            if isinstance(img, np.ndarray):
                pil_images.append(Image.fromarray(img))
            else:
                pil_images.append(img)
                
        try:
            inputs = self.processor(images=pil_images, return_tensors="pt", padding=True).to(self.device)
            with torch.no_grad():
                outputs = self.model.get_image_features(**inputs)
                image_features = outputs.pooler_output if hasattr(outputs, "pooler_output") else outputs
                image_features = image_features / image_features.norm(dim=-1, keepdim=True)
                return image_features.cpu().numpy().tolist()
        except Exception as e:
            logger.error(f"Error generating visual CLIP embeddings: {str(e)}")
            return []

    def get_text_embedding(self, text: str) -> List[float]:
        """
        Generates a normalized 512-dimensional semantic embedding for a text search query.
        """
        if not text:
            return []
            
        try:
            inputs = self.processor(text=[text], return_tensors="pt", padding=True).to(self.device)
            with torch.no_grad():
                outputs = self.model.get_text_features(**inputs)
                text_features = outputs.pooler_output if hasattr(outputs, "pooler_output") else outputs
                text_features = text_features / text_features.norm(dim=-1, keepdim=True)
                return text_features.cpu().numpy()[0].tolist()
        except Exception as e:
            logger.error(f"Error generating text CLIP embedding for '{text}': {str(e)}")
            return []
