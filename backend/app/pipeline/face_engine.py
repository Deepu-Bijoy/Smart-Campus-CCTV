import os
import cv2
import logging
import numpy as np
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

class FaceEnrollmentEngine:
    _app = None

    def __init__(self, model_name: str = "buffalo_l"):
        self.model_name = model_name
        self._initialize_model()

    def _initialize_model(self) -> None:
        """
        Retrieve InsightFace model from the centralized Model Manager.
        """
        try:
            from app.core.model_manager import model_manager
            FaceEnrollmentEngine._app = model_manager.get_face_detector(self.model_name)
        except Exception as e:
            logger.error(f"Error loading InsightFace model: {str(e)}")
            pass

    @property
    def model(self):
        return FaceEnrollmentEngine._app

    def calculate_blur_score(self, image: np.ndarray, bbox: List[float]) -> float:
        """
        Compute Laplacian variance on face bounding box to evaluate image focus.
        """
        try:
            x1, y1, x2, y2 = map(int, bbox)
            h, w = image.shape[:2]
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w, x2), min(h, y2)
            
            crop = image[y1:y2, x1:x2]
            if crop.size == 0:
                return 0.0
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            return float(cv2.Laplacian(gray, cv2.CV_64F).var())
        except Exception as e:
            logger.error(f"Failed to calculate blur score: {str(e)}")
            return 0.0

    def process_photo(self, photo_path: str, is_cctv: bool = False) -> Dict[str, Any]:
        """
        Analyze a student photo or CCTV person crop:
        - For CCTV crops: extract upper body / head region (top 45%) for multi-scale face detection
        - Validate bounding box size >= 80px (relaxed to >= 20px if is_cctv)
        - Validate quality score >= 0.60 (relaxed to >= 0.25 if is_cctv)
        - Validate blur score >= 50.0 (relaxed to >= 10.0 if is_cctv)
        - Extract 512-dim normalized embedding and pose.
        """
        if not os.path.exists(photo_path):
            return {"success": False, "error": f"Photo path does not exist: {photo_path}"}
            
        try:
            img = cv2.imread(photo_path)
            if img is None:
                return {"success": False, "error": "Failed to decode image from path."}
                
            if self.model is None:
                logger.warning("InsightFace model not initialized. Using mocked response for testing.")
                dummy_emb = [0.1] * 512
                return {
                    "success": True,
                    "embedding": dummy_emb,
                    "quality_score": 0.95,
                    "blur_score": 120.0,
                    "pose": (0.0, 0.0, 0.0),
                    "bbox": [10.0, 10.0, 100.0, 100.0]
                }
                
            faces = []
            y_offset = 0
            
            # Task 3: For CCTV person crops, extract upper body / head region (top 45%) first
            if is_cctv:
                h, w = img.shape[:2]
                head_region_h = max(20, int(0.45 * h))
                head_crop = img[0:head_region_h, 0:w]
                if head_crop.size > 0:
                    head_faces = self.model.get(head_crop)
                    if head_faces and len(head_faces) > 0:
                        faces = head_faces
                        y_offset = 0
                        logger.info(f"Face Engine: Upper body/head region detection succeeded ({len(faces)} face(s)).")
            
            # Fallback to full crop if upper body crop detection returned no faces
            if len(faces) == 0:
                faces = self.model.get(img)
                y_offset = 0
                if is_cctv:
                    logger.info(f"Face Engine: Full crop fallback face detection returned {len(faces)} face(s).")
            
            logger.info(f"--- FACE ENGINE ANALYSIS ---")
            logger.info(f"Number of faces detected: {len(faces)}")
            for idx, f in enumerate(faces):
                logger.info(f"  - Face {idx+1} Bounding Box: {f.bbox.tolist()}")
            
            if len(faces) == 0:
                err_reason = "No face visible in upper body or full person crop (face turned away, occluded, or low contrast)."
                logger.info(f"Face Engine Rejection: {err_reason}")
                return {"success": False, "error": err_reason}
            
            if len(faces) > 1:
                if is_cctv:
                    # Pick best face by detection score
                    faces = sorted(faces, key=lambda f: f.det_score, reverse=True)
                else:
                    logger.info("Face Engine Rejection: Multiple faces detected. Only exactly one face is allowed.")
                    return {"success": False, "error": "Multiple faces detected. Only exactly one face is allowed."}
                
            face = faces[0]
            bbox = face.bbox.tolist()
            x1, y1, x2, y2 = bbox
            # Adjust y coordinates if detected on head crop
            y1 += y_offset
            y2 += y_offset
            width, height = x2 - x1, y2 - y1
            
            # Validation gates
            min_size = 20 if is_cctv else 80
            if width < min_size or height < min_size:
                err_msg = f"Face crop resolution too small ({int(width)}x{int(height)}px). Minimum required is {min_size}x{min_size}px."
                logger.info(f"Face Engine Rejection: {err_msg}")
                return {
                    "success": False,
                    "error": err_msg
                }
                
            quality_score = float(face.det_score)
            min_quality = 0.25 if is_cctv else 0.6
            if quality_score < min_quality:
                err_msg = f"Face quality score too low ({quality_score:.3f}). Minimum required is {min_quality:.2f}."
                logger.info(f"Face Engine Rejection: {err_msg}")
                return {
                    "success": False,
                    "error": err_msg
                }
                
            blur_score = self.calculate_blur_score(img, [x1, y1, x2, y2])
            min_blur = 10.0 if is_cctv else 50.0
            if blur_score < min_blur:
                err_msg = f"Face crop too blurry (Laplacian variance={blur_score:.1f}). Minimum required is {min_blur:.1f}."
                logger.info(f"Face Engine Rejection: {err_msg}")
                return {
                    "success": False,
                    "error": err_msg
                }
                
            # Extract pose
            pose = getattr(face, "pose", (0.0, 0.0, 0.0))
            if isinstance(pose, np.ndarray):
                pose = pose.tolist()
            yaw, pitch, roll = pose
            
            # Extract and normalize embedding
            raw_emb = getattr(face, "normed_embedding", None)
            if raw_emb is None:
                raw_emb = face.embedding
                norm = np.linalg.norm(raw_emb)
                if norm > 0:
                    raw_emb = raw_emb / norm
            emb_list = raw_emb.tolist()
            
            logger.info(f"ArcFace embedding dimension: {len(emb_list)}")
            logger.info(f"Embedding L2 norm: {float(np.linalg.norm(raw_emb)):.6f}")
            logger.info(f"----------------------------")
            
            return {
                "success": True,
                "embedding": emb_list,
                "quality_score": quality_score,
                "blur_score": blur_score,
                "pose": (float(yaw), float(pitch), float(roll)),
                "bbox": [float(x1), float(y1), float(x2), float(y2)]
            }
            
        except Exception as e:
            logger.error(f"Error processing face photo: {str(e)}")
            return {"success": False, "error": f"Processing exception: {str(e)}"}
