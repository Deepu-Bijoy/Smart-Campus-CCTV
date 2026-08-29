try:
    import torch
except ImportError:
    torch = None
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# ── Graceful imports: models are loaded lazily, server starts without them ──
try:
    from ultralytics import YOLO as _YOLO
except ImportError:
    _YOLO = None
    logger.warning("ultralytics not installed — YOLOv8 detection disabled.")

try:
    from transformers import CLIPProcessor, CLIPModel as _CLIPModel
    _CLIPProcessor = CLIPProcessor
except ImportError:
    _CLIPModel = None
    _CLIPProcessor = None
    logger.warning("transformers not installed — CLIP embeddings disabled.")

try:
    from torchreid.utils import FeatureExtractor as _FeatureExtractor
except ImportError:
    try:
        from torchreid.reid.utils import FeatureExtractor as _FeatureExtractor
    except ImportError:
        _FeatureExtractor = None
        logger.warning("torchreid not installed — OSNet Re-ID disabled.")

try:
    from insightface.app import FaceAnalysis as _FaceAnalysis
except ImportError:
    _FaceAnalysis = None
    logger.warning("insightface not installed — ArcFace face recognition disabled.")

from typing import Any
FaceAnalysis = Any


class AIModelManager:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(AIModelManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.use_fp16 = self.device == "cuda"
        
        self._yolo = None
        self._clip_model = None
        self._clip_processor = None
        self._osnet = None
        self._insightface = None

        self._lock = threading.Lock()
        self._initialized = True
        logger.info(f"Initialized Centralized AI Model Manager on device: {self.device} (FP16: {self.use_fp16})")

    def get_yolo(self, model_name: str = "yolov8n.pt"):
        if _YOLO is None:
            raise RuntimeError("ultralytics is not installed. Run: pip install ultralytics")
        if self._yolo is None:
            with self._lock:
                if self._yolo is None:
                    logger.info(f"Loading YOLOv8 model ({model_name})...")
                    self._yolo = _YOLO(model_name)
        return self._yolo

    def get_clip(self, model_name: str = "openai/clip-vit-base-patch32") -> tuple:
        if _CLIPModel is None:
            raise RuntimeError("transformers is not installed. Run: pip install transformers")
        if self._clip_model is None or self._clip_processor is None:
            with self._lock:
                if self._clip_model is None or self._clip_processor is None:
                    logger.info(f"Loading CLIP model ({model_name})...")
                    self._clip_model = _CLIPModel.from_pretrained(model_name).to(self.device)
                    self._clip_processor = _CLIPProcessor.from_pretrained(model_name)
                    self._clip_model.eval()
        return self._clip_model, self._clip_processor

    def get_osnet(self, model_name: str = "osnet_x1_0"):
        if _FeatureExtractor is None:
            raise RuntimeError("torchreid is not installed. Install from: https://github.com/KaiyangZhou/deep-person-reid")
        if self._osnet is None:
            with self._lock:
                if self._osnet is None:
                    logger.info(f"Loading torchreid OSNet FeatureExtractor ({model_name})...")
                    self._osnet = _FeatureExtractor(
                        model_name=model_name,
                        device=self.device,
                        verbose=False
                    )
        return self._osnet

    def _get_insightface(self, model_name: str = "buffalo_l"):
        if _FaceAnalysis is None:
            raise RuntimeError("insightface is not installed. Run: pip install insightface onnxruntime")
        if self._insightface is None:
            with self._lock:
                if self._insightface is None:
                    logger.info(f"Loading InsightFace FaceAnalysis '{model_name}'...")
                    app = _FaceAnalysis(name=model_name, root="storage/models/insightface")
                    ctx_id = 0 if self.device == "cuda" else -1
                    app.prepare(ctx_id=ctx_id, det_size=(640, 640))
                    self._insightface = app
        return self._insightface

    def get_face_detector(self, model_name: str = "buffalo_l") -> FaceAnalysis:
        return self._get_insightface(model_name)

    def get_arcface(self, model_name: str = "buffalo_l") -> FaceAnalysis:
        return self._get_insightface(model_name)

    def warmup_all_models(self):
        logger.info("Warming up all AI models for production deployment...")
        print("====================================================")
        print("AI MODELS WARMUP STATUS & DEVICE DETAILS")
        print("====================================================")
        if torch is not None:
            print(f"Torch Version: {torch.__version__}")
            print(f"CUDA Available: {torch.cuda.is_available()}")
            if torch.cuda.is_available():
                print(f"GPU Name: {torch.cuda.get_device_name(0)}")
            else:
                print("GPU Name: None")
        else:
            print("Torch is not installed or available.")
        
        try:
            # 1. YOLOv8
            yolo = self.get_yolo()
            print(f"- YOLOv8 Device: {getattr(yolo, 'device', 'cpu')}")
            
            # 2. CLIP
            clip_model, _ = self.get_clip()
            print(f"- CLIP Device: {getattr(clip_model, 'device', 'cpu')}")
            
            # 3. OSNet
            osnet = self.get_osnet()
            osnet_device = next(osnet.model.parameters()).device if hasattr(osnet, 'model') else self.device
            print(f"- OSNet Re-ID Device: {osnet_device}")
            
            # 4. InsightFace / ArcFace
            insightface = self._get_insightface()
            print(f"- InsightFace/ArcFace Device: {self.device}")
            
            print("====================================================")
            logger.info("All AI models warmed up successfully!")
        except Exception as e:
            logger.error(f"Error during AI models warmup: {str(e)}")
            print(f"Warmup Failed: {str(e)}")
            print("====================================================")

model_manager = AIModelManager()
