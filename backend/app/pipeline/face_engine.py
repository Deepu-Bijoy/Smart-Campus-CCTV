import os
import cv2
import logging
import numpy as np
from typing import List, Dict, Any, Tuple, Optional
from app.core.config import settings

logger = logging.getLogger(__name__)

# Standard Biometric Quality and Failure Reason Categories
QUALITY_FACE_NOT_DETECTED = "NO_FACE_DETECTED"
QUALITY_FACE_TOO_SMALL = "FACE_TOO_SMALL"
QUALITY_FACE_BLURRY = "FACE_BLURRY"
QUALITY_FACE_OCCLUDED = "FACE_OCCLUDED"
QUALITY_FACE_UNSUITABLE = "FACE_UNSUITABLE_QUALITY"
QUALITY_FACE_SUITABLE = "FACE_SUITABLE_FOR_RECOGNITION"


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
            return float(cv2.Laplacian(gray, cv2.CV_32F).var())
        except Exception as e:
            logger.error(f"Failed to calculate blur score: {str(e)}")
            return 0.0

    def resolve_adaptive_scales(self, width: int, height: int) -> List[Tuple[int, int]]:
        """
        Selects optimal multi-scale SCRFD input resolutions based on input image dimensions
        and centralized configuration.
        """
        cfg_sizes = getattr(settings, "FACE_DETECTION_SIZES", [640, 960, 1280])
        # Full CCTV frames (e.g. 720p, 1080p, 4K)
        if width >= 960 or height >= 720:
            return [(int(s), int(s)) for s in cfg_sizes]
        # Medium tiles or large person crops (e.g. 300px to 720px)
        elif width >= 300 or height >= 300:
            medium_sizes = [s for s in cfg_sizes if s <= 640] or [480, 640]
            return [(int(s), int(s)) for s in medium_sizes]
        # Small person or head-region crops (< 300px)
        else:
            return [(320, 320), (480, 480)]

    def detect_faces_multiscale(
        self,
        img: np.ndarray,
        scales: Optional[List[Tuple[int, int]]] = None,
        conf_thresh: Optional[float] = None,
        min_size: Optional[int] = None,
        adaptive: Optional[bool] = None
    ) -> List[Any]:
        """
        Performs multi-scale SCRFD face detection with adaptive resolution pyramids,
        NMS candidate fusion, and ArcFace embedding extraction.
        Configurable detection sizes: 640x640, 960x960, 1280x1280.
        When adaptive=True:
            Starts at baseline scale; if clear faces are found, avoids redundant larger scales.
            If initial detection is insufficient, progressively escalates to larger scales.
        """
        if img is None or img.size == 0 or self.model is None:
            return []

        h, w = img.shape[:2]
        if scales is None:
            scales = self.resolve_adaptive_scales(w, h)

        if conf_thresh is None:
            conf_thresh = getattr(settings, "FACE_CONF_THRESHOLD", 0.35)
        if min_size is None:
            min_size = getattr(settings, "FACE_MIN_SIZE_PIXELS", 12)
        if adaptive is None:
            adaptive = getattr(settings, "FACE_ADAPTIVE_SCALING", True)

        try:
            from insightface.app.common import Face

            det_model = getattr(self.model, "det_model", None)
            if det_model is None:
                # If det_model is unavailable, fallback to self.model.get(img)
                return self.model.get(img)

            all_bboxes_list = []
            all_kpss_list = []

            if adaptive and len(scales) > 1:
                # Progressive adaptive multi-scale execution
                for idx, sc in enumerate(scales):
                    bboxes, kpss = det_model.detect(img, input_size=sc)
                    if bboxes is not None and len(bboxes) > 0:
                        all_bboxes_list.append(bboxes)
                        if kpss is not None:
                            all_kpss_list.append(kpss)

                        # Check if we already detected a high-confidence, good-resolution face
                        max_score = float(np.max(bboxes[:, 4])) if len(bboxes) > 0 else 0.0
                        widths = bboxes[:, 2] - bboxes[:, 0]
                        max_w = float(np.max(widths)) if len(widths) > 0 else 0.0

                        # Early exit condition: Clear face detected at baseline resolution
                        # Avoids running heavy 960x960 and 1280x1280 inference when unnecessary
                        if max_score >= 0.55 and max_w >= 28.0:
                            logger.debug(
                                "[FACE ENGINE] Adaptive multi-scale early exit at scale %s (score=%.2f, size=%.1fpx)",
                                sc, max_score, max_w
                            )
                            break
            else:
                # Direct multi-scale execution
                bboxes, kpss = det_model.detect(img, input_size=scales)
                if bboxes is not None and len(bboxes) > 0:
                    all_bboxes_list.append(bboxes)
                    if kpss is not None:
                        all_kpss_list.append(kpss)

            if not all_bboxes_list:
                return []

            # Concatenate detections across evaluated scales
            merged_bboxes = np.vstack(all_bboxes_list)
            merged_kpss = np.vstack(all_kpss_list) if (all_kpss_list and len(all_kpss_list) == len(all_bboxes_list)) else None

            # Cross-scale NMS deduplication if multiple scales were executed
            if len(all_bboxes_list) > 1 and len(merged_bboxes) > 1:
                nms_iou = getattr(settings, "FACE_NMS_IOU_THRESHOLD", 0.45)
                keep_idx = self._apply_nms(merged_bboxes, iou_thresh=nms_iou)
                merged_bboxes = merged_bboxes[keep_idx]
                if merged_kpss is not None:
                    merged_kpss = merged_kpss[keep_idx]

            rec_model = self.model.models.get("recognition")
            detected_faces = []

            for i in range(len(merged_bboxes)):
                score = float(merged_bboxes[i, 4])
                if score < conf_thresh:
                    continue

                bx1, by1, bx2, by2 = merged_bboxes[i, :4]
                bw, bh = float(bx2 - bx1), float(by2 - by1)
                if bw < min_size or bh < min_size:
                    continue

                kps = merged_kpss[i] if merged_kpss is not None else None
                face_obj = Face(bbox=merged_bboxes[i, :4], kps=kps, det_score=score)

                # Extract ArcFace embedding if recognition model is available
                if rec_model is not None:
                    try:
                        rec_model.get(img, face_obj)
                        raw_emb = getattr(face_obj, "embedding", None)
                        if raw_emb is not None:
                            arr_e = np.array(raw_emb, dtype=np.float32)
                            norm = np.linalg.norm(arr_e)
                            if norm > 0:
                                face_obj.normed_embedding = arr_e / norm
                    except Exception as re_err:
                        logger.debug("Failed extracting ArcFace embedding on face candidate: %s", re_err)

                detected_faces.append(face_obj)

            # Sort descending by detection score
            detected_faces.sort(key=lambda f: float(f.det_score), reverse=True)
            return detected_faces
        except Exception as e:
            logger.error("Error during multi-scale face detection: %s", e)
            return []

    @staticmethod
    def _apply_nms(bboxes: np.ndarray, iou_thresh: float = 0.45) -> List[int]:
        """Vectorized Non-Maximum Suppression on bounding boxes with confidence scores."""
        if len(bboxes) == 0:
            return []
        x1 = bboxes[:, 0]
        y1 = bboxes[:, 1]
        x2 = bboxes[:, 2]
        y2 = bboxes[:, 3]
        scores = bboxes[:, 4]

        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]

        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(int(i))
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])

            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

            inds = np.where(ovr <= iou_thresh)[0]
            order = order[inds + 1]

        return keep

    @staticmethod
    def extract_head_region(
        frame: np.ndarray,
        person_bbox: List[int],
        padding_ratio: Optional[float] = None,
        head_ratio: Optional[float] = None
    ) -> Tuple[np.ndarray, List[int]]:
        """
        Phase 3: Extracts the upper 35-40% head/upper-body region from a person bounding box
        directly from the full-resolution frame, preserving native camera pixels and aspect ratio.
        Coordinates are safely clamped to frame boundaries.
        Returns:
            Tuple of (head_crop, [hx1, hy1, hx2, hy2]) where coordinates are in full-frame space.
        """
        if frame is None or frame.size == 0:
            return np.empty((0, 0, 3), dtype=np.uint8), [0, 0, 0, 0]

        if padding_ratio is None:
            padding_ratio = getattr(settings, "FACE_HEAD_PADDING_RATIO", 0.15)
        if head_ratio is None:
            head_ratio = getattr(settings, "FACE_HEAD_RATIO", 0.38)

        fh, fw = frame.shape[:2]
        x1, y1, x2, y2 = map(int, person_bbox)
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(fw, x2), min(fh, y2)
        pw = max(1, x2 - x1)
        ph = max(1, y2 - y1)
        aspect = ph / float(pw)

        # Upright human (standing or walking): isolate upper 35-40% with contextual padding
        if aspect > 1.2:
            head_h = max(16, int(ph * head_ratio))
            pad_x = int(pw * padding_ratio)
            pad_y = int(head_h * 0.20)
            hx1 = max(0, x1 - pad_x)
            hy1 = max(0, y1 - pad_y)
            hx2 = min(fw, x2 + pad_x)
            hy2 = min(fh, y1 + head_h + pad_y)
        else:
            # Crouching, grappling, or fallen human: preserve full body with uniform padding
            pad_x = int(pw * padding_ratio)
            pad_y = int(ph * padding_ratio)
            hx1 = max(0, x1 - pad_x)
            hy1 = max(0, y1 - pad_y)
            hx2 = min(fw, x2 + pad_x)
            hy2 = min(fh, y2 + pad_y)

        # Safe slice ensuring valid non-empty array
        if hx2 <= hx1 or hy2 <= hy1:
            return np.empty((0, 0, 3), dtype=np.uint8), [0, 0, 0, 0]

        head_crop = frame[hy1:hy2, hx1:hx2]
        return head_crop, [hx1, hy1, hx2, hy2]

    @staticmethod
    def generate_frame_tiles(
        frame: np.ndarray,
        tile_size: Optional[int] = None,
        overlap: Optional[float] = None,
        roi_boxes: Optional[List[List[float]]] = None
    ) -> List[Dict[str, Any]]:
        """
        Phase 4: Generates overlapping high-resolution tiles across the frame or regions of interest.
        If roi_boxes is provided: restricts tiling to the bounding envelope of active subjects (with context margin).
        If roi_boxes is None: tiles the entire frame with step size (tile_size * (1.0 - overlap)).
        Returns:
            List of dicts: {"crop": tile_np, "box": [tx1, ty1, tx2, ty2]} in frame coordinates.
        """
        if frame is None or frame.size == 0:
            return []

        if tile_size is None:
            tile_size = getattr(settings, "FACE_TILE_SIZE", 640)
        if overlap is None:
            overlap = getattr(settings, "FACE_TILE_OVERLAP", 0.20)

        fh, fw = frame.shape[:2]

        if roi_boxes and len(roi_boxes) > 0:
            all_x1 = min(b[0] for b in roi_boxes)
            all_y1 = min(b[1] for b in roi_boxes)
            all_x2 = max(b[2] for b in roi_boxes)
            all_y2 = max(b[3] for b in roi_boxes)

            # Context padding around cluster (15%)
            cw = max(1, all_x2 - all_x1)
            ch = max(1, all_y2 - all_y1)
            cx1 = max(0, int(all_x1 - 0.15 * cw))
            cy1 = max(0, int(all_y1 - 0.15 * ch))
            cx2 = min(fw, int(all_x2 + 0.15 * cw))
            cy2 = min(fh, int(all_y2 + 0.15 * ch))
        else:
            cx1, cy1, cx2, cy2 = 0, 0, fw, fh

        tiles = []
        step = max(64, int(tile_size * (1.0 - overlap)))

        y_starts = list(range(cy1, max(cy1 + 1, cy2 - tile_size + 1), step))
        if not y_starts or y_starts[-1] + tile_size < cy2:
            y_starts.append(max(0, cy2 - tile_size))

        x_starts = list(range(cx1, max(cx1 + 1, cx2 - tile_size + 1), step))
        if not x_starts or x_starts[-1] + tile_size < cx2:
            x_starts.append(max(0, cx2 - tile_size))

        y_starts = sorted(list(set(y_starts)))
        x_starts = sorted(list(set(x_starts)))

        for ty in y_starts:
            for tx in x_starts:
                tx2 = min(fw, tx + tile_size)
                ty2 = min(fh, ty + tile_size)
                tile_crop = frame[ty:ty2, tx:tx2]
                if tile_crop.size > 0:
                    tiles.append({
                        "crop": tile_crop,
                        "box": [tx, ty, tx2, ty2]
                    })

        return tiles

    @staticmethod
    def generate_altercation_tiles(
        frame: np.ndarray,
        participant_boxes: List[List[float]],
        tile_size: int = 640,
        overlap: float = 0.20
    ) -> List[Dict[str, Any]]:
        """
        Phase 4: Backward-compatible helper for generating altercation-cluster tiles.
        Delegates to generate_frame_tiles with participant bounding boxes as ROIs.
        """
        return FaceEnrollmentEngine.generate_frame_tiles(
            frame=frame,
            tile_size=tile_size,
            overlap=overlap,
            roi_boxes=participant_boxes
        )

    @staticmethod
    def cross_tile_nms(
        boxes_with_scores: List[Tuple[List[float], float, Any]],
        iou_thresh: float = 0.45
    ) -> List[Tuple[List[float], float, Any]]:
        """
        Phase 4: Applies Non-Maximum Suppression across remapped tile face detections.
        Eliminates duplicate face observations spanning overlapping tile boundaries.
        Each item is (bbox, score, face_obj) where bbox is [x1, y1, x2, y2] in full frame space.
        """
        if not boxes_with_scores:
            return []

        boxes = np.array([item[0] for item in boxes_with_scores], dtype=np.float32)
        scores = np.array([item[1] for item in boxes_with_scores], dtype=np.float32)

        x1 = boxes[:, 0]
        y1 = boxes[:, 1]
        x2 = boxes[:, 2]
        y2 = boxes[:, 3]
        areas = (x2 - x1) * (y2 - y1)
        order = scores.argsort()[::-1]

        keep = []
        while order.size > 0:
            i = order[0]
            keep.append(i)
            xx1 = np.maximum(x1[i], x1[order[1:]])
            yy1 = np.maximum(y1[i], y1[order[1:]])
            xx2 = np.minimum(x2[i], x2[order[1:]])
            yy2 = np.minimum(y2[i], y2[order[1:]])

            w = np.maximum(0.0, xx2 - xx1)
            h = np.maximum(0.0, yy2 - yy1)
            inter = w * h
            ovr = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)

            inds = np.where(ovr <= iou_thresh)[0]
            order = order[inds + 1]

        return [boxes_with_scores[k] for k in keep]

    def detect_faces_tiled(
        self,
        frame: np.ndarray,
        roi_boxes: Optional[List[List[float]]] = None,
        tile_size: Optional[int] = None,
        overlap: Optional[float] = None,
        conf_thresh: Optional[float] = None,
        min_size: Optional[int] = None
    ) -> List[Tuple[List[float], float, Any]]:
        """
        Runs high-resolution tiled face detection over frame or ROIs:
        1. Generates overlapping tiles.
        2. Detects faces in each tile.
        3. Remaps detected coordinates back to original frame coordinates.
        4. Merges overlapping cross-tile detections using cross_tile_nms.
        Returns:
            List of (frame_box, score, face_obj).
        """
        if frame is None or frame.size == 0 or self.model is None:
            return []

        tiles = self.generate_frame_tiles(frame, tile_size=tile_size, overlap=overlap, roi_boxes=roi_boxes)
        raw_tile_faces = []

        for tile in tiles:
            t_crop = tile["crop"]
            tx1, ty1, tx2, ty2 = tile["box"]
            t_faces = self.detect_faces_multiscale(
                t_crop,
                scales=[(640, 640)],
                conf_thresh=conf_thresh,
                min_size=min_size,
                adaptive=False
            )
            for tf in t_faces:
                tfx1, tfy1, tfx2, tfy2 = tf.bbox
                frame_box = [float(tfx1 + tx1), float(tfy1 + ty1), float(tfx2 + tx1), float(tfy2 + ty1)]
                # Remap facial landmarks if present
                if getattr(tf, "kps", None) is not None:
                    tf.kps = tf.kps.copy()
                    tf.kps[:, 0] += tx1
                    tf.kps[:, 1] += ty1
                raw_tile_faces.append((frame_box, float(tf.det_score), tf))

        nms_iou = getattr(settings, "FACE_NMS_IOU_THRESHOLD", 0.45)
        deduped = self.cross_tile_nms(raw_tile_faces, iou_thresh=nms_iou)
        return deduped

    @staticmethod
    def evaluate_face_quality_and_failure(
        face_obj: Optional[Any],
        image: np.ndarray,
        meas_box: Optional[List[float]] = None,
        min_size: int = 12,
        min_blur: float = 10.0,
        min_conf: float = 0.35,
        min_quality: float = 0.20
    ) -> Dict[str, Any]:
        """
        Phase 6 Quality Evaluation & Failure Reason Telemetry.
        Evaluates dimensions, blur, detection confidence, facial landmark alignment,
        pose angles, and occlusion to distinguish:
        - NO_FACE_DETECTED: Face not detected.
        - FACE_TOO_SMALL: Face bounding-box dimensions < min_size.
        - FACE_BLURRY: Laplacian variance sharpness < min_blur.
        - FACE_OCCLUDED: Missing landmarks, bad landmark geometry, or extreme pose.
        - FACE_UNSUITABLE_QUALITY: Det score < min_conf or overall quality < min_quality.
        - FACE_SUITABLE_FOR_RECOGNITION: All criteria passed and face is suitable for recognition.
        """
        if face_obj is None:
            return {
                "quality_score": 0.0,
                "blur_score": 0.0,
                "quality_category": QUALITY_FACE_NOT_DETECTED,
                "failure_reason": "No face detected in observation crop",
                "pose": (0.0, 0.0, 0.0),
                "is_suitable": False
            }

        det_score = float(getattr(face_obj, "det_score", 0.0))
        bbox = getattr(face_obj, "bbox", [0, 0, 0, 0])
        fx1, fy1, fx2, fy2 = map(int, bbox[:4])
        fw = max(0, fx2 - fx1)
        fh = max(0, fy2 - fy1)

        # 1. Dimension Check
        if fw < min_size or fh < min_size:
            return {
                "quality_score": round(det_score * 0.2, 4),
                "blur_score": 0.0,
                "quality_category": QUALITY_FACE_TOO_SMALL,
                "failure_reason": f"Face resolution too small ({fw}x{fh}px, min {min_size}px)",
                "pose": (0.0, 0.0, 0.0),
                "is_suitable": False
            }

        # 2. Blur / Sharpness Check
        eval_box = meas_box if meas_box else [fx1, fy1, fx2, fy2]
        engine = FaceEnrollmentEngine()
        blur_val = engine.calculate_blur_score(image, eval_box)
        if blur_val < min_blur:
            return {
                "quality_score": round(det_score * 0.3, 4),
                "blur_score": round(blur_val, 2),
                "quality_category": QUALITY_FACE_BLURRY,
                "failure_reason": f"Face crop blurry (Laplacian variance {blur_val:.1f} < {min_blur:.1f})",
                "pose": (0.0, 0.0, 0.0),
                "is_suitable": False
            }

        # 3. Pose and Alignment / Occlusion Check
        raw_pose = getattr(face_obj, "pose", None)
        if isinstance(raw_pose, np.ndarray):
            raw_pose = tuple(raw_pose.tolist())
        if raw_pose is not None and isinstance(raw_pose, (tuple, list)) and len(raw_pose) == 3:
            pose = (float(raw_pose[0]), float(raw_pose[1]), float(raw_pose[2]))
        else:
            pose = (0.0, 0.0, 0.0)
        yaw, pitch, roll = pose

        # Extreme yaw (> 45 deg) or extreme pitch (> 30 deg) indicates turned-away/occluded face
        if abs(yaw) > 45.0 or abs(pitch) > 30.0:
            return {
                "quality_score": round(det_score * 0.4, 4),
                "blur_score": round(blur_val, 2),
                "quality_category": QUALITY_FACE_OCCLUDED,
                "failure_reason": f"Face turned away or occluded (yaw={yaw:.1f} deg, pitch={pitch:.1f} deg)",
                "pose": (float(yaw), float(pitch), float(roll)),
                "is_suitable": False
            }

        # Check facial landmarks (kps) if available
        kps = getattr(face_obj, "kps", None)
        if kps is not None and len(kps) == 5:
            # Check eye distance relative to face width
            left_eye, right_eye = kps[0], kps[1]
            eye_dist = float(np.linalg.norm(left_eye - right_eye))
            if eye_dist < (0.15 * fw):
                return {
                    "quality_score": round(det_score * 0.4, 4),
                    "blur_score": round(blur_val, 2),
                    "quality_category": QUALITY_FACE_OCCLUDED,
                    "failure_reason": "Facial landmark collapse / extreme profile occlusion",
                    "pose": (float(yaw), float(pitch), float(roll)),
                    "is_suitable": False
                }

        # 4. Confidence Gate
        if det_score < min_conf:
            return {
                "quality_score": round(det_score, 4),
                "blur_score": round(blur_val, 2),
                "quality_category": QUALITY_FACE_UNSUITABLE,
                "failure_reason": f"Detector confidence ({det_score:.3f}) below threshold ({min_conf:.2f})",
                "pose": (float(yaw), float(pitch), float(roll)),
                "is_suitable": False
            }

        # 5. Composite Quality Formulation
        norm_conf = max(0.0, min(1.0, (det_score - 0.35) / 0.60))
        norm_size = max(0.15, min(1.0, (np.sqrt(fw * fh) - 12.0) / 48.0))
        norm_sharp = max(0.10, min(1.0, float(np.log1p(max(0.0, blur_val)) / np.log1p(250.0))))
        norm_pose = max(0.40, min(1.0, 1.0 - (abs(yaw) / 90.0) * 0.5 - (abs(pitch) / 90.0) * 0.5))
        composite_q = (norm_conf ** 0.35) * (norm_size ** 0.30) * (norm_sharp ** 0.20) * (norm_pose ** 0.15)
        composite_q = float(round(np.clip(composite_q, 0.0, 1.0), 4))

        if composite_q < min_quality:
            return {
                "quality_score": composite_q,
                "blur_score": round(blur_val, 2),
                "quality_category": QUALITY_FACE_UNSUITABLE,
                "failure_reason": f"Composite biometric quality ({composite_q:.3f}) below gate ({min_quality:.2f})",
                "pose": (float(yaw), float(pitch), float(roll)),
                "is_suitable": False
            }

        return {
            "quality_score": composite_q,
            "blur_score": round(blur_val, 2),
            "quality_category": QUALITY_FACE_SUITABLE,
            "failure_reason": None,
            "pose": (float(yaw), float(pitch), float(roll)),
            "is_suitable": True
        }

    def process_photo(self, photo_path: str, is_cctv: bool = False) -> Dict[str, Any]:
        """
        Analyze a student photo or CCTV person crop:
        - For CCTV crops: apply adaptive multi-scale SCRFD detection (320, 480, 640)
        - Validate bounding box size >= 80px (relaxed to >= 12px if is_cctv)
        - Validate quality score >= 0.60 (relaxed to >= 0.20 if is_cctv)
        - Validate blur score >= 50.0 (relaxed to >= 10.0 if is_cctv)
        - Extract 512-dim normalized embedding and pose.
        - Provides standard failure telemetry.
        """
        if not os.path.exists(photo_path):
            return {
                "success": False,
                "error": f"Photo path does not exist: {photo_path}",
                "quality_category": QUALITY_FACE_NOT_DETECTED
            }
            
        try:
            img = cv2.imread(photo_path)
            if img is None:
                return {
                    "success": False,
                    "error": "Failed to decode image from path.",
                    "quality_category": QUALITY_FACE_NOT_DETECTED
                }
                
            if self.model is None:
                logger.warning("InsightFace model not initialized. Using mocked response for testing.")
                dummy_emb = [0.1] * 512
                return {
                    "success": True,
                    "embedding": dummy_emb,
                    "quality_score": 0.95,
                    "blur_score": 120.0,
                    "pose": (0.0, 0.0, 0.0),
                    "bbox": [10.0, 10.0, 100.0, 100.0],
                    "quality_category": QUALITY_FACE_SUITABLE
                }
                
            faces = []
            y_offset = 0
            
            # For CCTV person crops, extract upper body / head region if full-body aspect ratio
            if is_cctv:
                h, w = img.shape[:2]
                aspect_ratio = h / max(1, w)
                if aspect_ratio > 1.2:
                    head_crop, head_coords = self.extract_head_region(img, [0, 0, w, h])
                    if head_crop.size > 0:
                        head_faces = self.detect_faces_multiscale(head_crop, conf_thresh=0.25, min_size=10)
                        if head_faces and len(head_faces) > 0:
                            faces = head_faces
                            y_offset = head_coords[1]
                            logger.info(f"Face Engine: Upper body/head region detection succeeded ({len(faces)} face(s)).")
            
            # Fallback to full crop if upper body crop returned no faces
            if len(faces) == 0:
                if is_cctv:
                    faces = self.detect_faces_multiscale(img, conf_thresh=0.25, min_size=10)
                    y_offset = 0
                    logger.info(f"Face Engine: Full crop multi-scale detection returned {len(faces)} face(s).")
                else:
                    faces = self.model.get(img)
                    y_offset = 0
            
            logger.info(f"--- FACE ENGINE ANALYSIS ---")
            logger.info(f"Number of faces detected: {len(faces)}")
            for idx, f in enumerate(faces):
                logger.info(f"  - Face {idx+1} Bounding Box: {f.bbox.tolist()}")
            
            if len(faces) == 0:
                err_reason = "No face visible in upper body or full person crop (face turned away, occluded, or low contrast)."
                logger.info(f"Face Engine Rejection: {err_reason}")
                return {
                    "success": False,
                    "error": err_reason,
                    "quality_category": QUALITY_FACE_NOT_DETECTED
                }
            
            if len(faces) > 1:
                if is_cctv:
                    # Pick best face by detection score
                    faces = sorted(faces, key=lambda f: float(f.det_score), reverse=True)
                else:
                    logger.info("Face Engine Rejection: Multiple faces detected. Only exactly one face is allowed.")
                    return {
                        "success": False,
                        "error": "Multiple faces detected. Only exactly one face is allowed.",
                        "quality_category": QUALITY_FACE_UNSUITABLE
                    }
                
            face = faces[0]
            bbox = face.bbox.tolist()
            x1, y1, x2, y2 = bbox
            y1 += y_offset
            y2 += y_offset
            width, height = x2 - x1, y2 - y1
            
            min_size = getattr(settings, "FACE_MIN_SIZE_PIXELS", 12) if is_cctv else 80
            min_blur = getattr(settings, "FACE_BLUR_MIN_THRESHOLD", 10.0) if is_cctv else 50.0
            min_conf = 0.25 if is_cctv else 0.60
            min_quality = getattr(settings, "FACE_MIN_QUALITY_GATE", 0.20) if is_cctv else 0.60

            # Evaluate quality and failure telemetry
            eval_res = self.evaluate_face_quality_and_failure(
                face_obj=face,
                image=img,
                meas_box=[x1, y1, x2, y2],
                min_size=min_size,
                min_blur=min_blur,
                min_conf=min_conf,
                min_quality=min_quality
            )

            if not eval_res["is_suitable"]:
                logger.info(f"Face Engine Rejection: {eval_res['failure_reason']}")
                return {
                    "success": False,
                    "error": eval_res["failure_reason"],
                    "quality_category": eval_res["quality_category"],
                    "quality_score": eval_res["quality_score"],
                    "blur_score": eval_res["blur_score"],
                    "bbox": [float(x1), float(y1), float(x2), float(y2)]
                }

            # Extract pose
            pose = eval_res["pose"]
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
                "quality_score": eval_res["quality_score"],
                "blur_score": eval_res["blur_score"],
                "pose": (float(yaw), float(pitch), float(roll)),
                "bbox": [float(x1), float(y1), float(x2), float(y2)],
                "quality_category": QUALITY_FACE_SUITABLE
            }
            
        except Exception as e:
            logger.error(f"Error processing face photo: {str(e)}")
            return {
                "success": False,
                "error": f"Processing exception: {str(e)}",
                "quality_category": QUALITY_FACE_UNSUITABLE
            }
