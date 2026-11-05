import logging
import os
import sys
import threading
from typing import Any, Dict, List, Optional

try:
    import torch
except ImportError:
    torch = None

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
        self._dll_dir_handle = None

        self._lock = threading.Lock()
        self._initialized = True
        logger.info(f"Initialized Centralized AI Model Manager on device: {self.device} (FP16: {self.use_fp16})")

    def _ensure_windows_cuda_dlls(self) -> None:
        """
        On Windows, register PyTorch's lib directory via os.add_dll_directory() so that
        onnxruntime-gpu can locate CUDA/cuDNN DLLs (e.g. cublas64_12.dll, cudart64_12.dll, cudnn64_9.dll).
        Idempotent: retains the returned directory handle to keep the directory in DLL search path
        for the lifetime of the model sessions.
        """
        if sys.platform != "win32":
            return
        if self._dll_dir_handle is not None:
            return  # Already registered

        if torch is None or not hasattr(torch, "__file__") or not torch.__file__:
            logger.warning("PyTorch not found or has no __file__; cannot register PyTorch lib directory for ONNX CUDA.")
            return

        try:
            torch_lib = os.path.join(os.path.dirname(torch.__file__), "lib")
            if os.path.isdir(torch_lib):
                if hasattr(os, "add_dll_directory"):
                    self._dll_dir_handle = os.add_dll_directory(torch_lib)
                    logger.info("Successfully registered PyTorch DLL directory for ONNX CUDA: %s", torch_lib)
                else:
                    logger.warning("os.add_dll_directory is not available on this platform.")
            else:
                logger.warning("PyTorch lib directory does not exist: %s", torch_lib)
        except Exception as e:
            logger.error("Failed to register PyTorch DLL directory for ONNX CUDA: %s", e)

    def get_yolo(self, model_name: str = "yolov8n.pt"):
        if _YOLO is None:
            raise RuntimeError("ultralytics is not installed. Run: pip install ultralytics")
        if self._yolo is None:
            with self._lock:
                if self._yolo is None:
                    logger.info(f"Loading YOLOv8 model ({model_name})...")
                    self._yolo = _YOLO(model_name)
                    if self.device == "cuda":
                        try:
                            self._yolo.to(self.device)
                        except Exception:
                            pass
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

    def get_insightface_session_providers(self) -> Dict[str, List[str]]:
        """
        Dynamically inspects all initialized InsightFace models and queries each underlying
        ONNX session for its actual execution providers. Does not assume hardcoded dictionary keys.
        """
        if self._insightface is None or not hasattr(self._insightface, "models"):
            return {}
        
        providers_map: Dict[str, List[str]] = {}
        for key, model_obj in self._insightface.models.items():
            class_name = type(model_obj).__name__
            model_identifier = f"{key} ({class_name})"
            sess = getattr(model_obj, "session", getattr(model_obj, "net", None))
            if sess is not None and hasattr(sess, "get_providers"):
                try:
                    providers_map[model_identifier] = list(sess.get_providers())
                except Exception as e:
                    providers_map[model_identifier] = [f"error: {e}"]
            else:
                providers_map[model_identifier] = ["no_session_found"]
        return providers_map

    def _get_insightface(self, model_name: str = "buffalo_l"):
        if _FaceAnalysis is None:
            raise RuntimeError("insightface is not installed. Run: pip install insightface onnxruntime")
        if self._insightface is None:
            with self._lock:
                if self._insightface is None:
                    # Register PyTorch lib DLL directory on Windows before session creation
                    if self.device == "cuda":
                        self._ensure_windows_cuda_dlls()

                    logger.info(f"Loading InsightFace FaceAnalysis '{model_name}'...")
                    app = _FaceAnalysis(name=model_name, root="storage/models/insightface")
                    
                    if self.device == "cuda":
                        try:
                            app.prepare(ctx_id=0, det_size=(640, 640))
                            logger.info("InsightFace prepared on CUDA (ctx_id=0).")
                        except Exception as e:
                            logger.error(
                                "Failed to initialize InsightFace on CUDA (ctx_id=0): %s. Falling back to CPU.",
                                e,
                                exc_info=True,
                            )
                            app.prepare(ctx_id=-1, det_size=(640, 640))
                            logger.info("InsightFace fallback prepared on CPU (ctx_id=-1).")
                    else:
                        app.prepare(ctx_id=-1, det_size=(640, 640))
                        logger.info("InsightFace prepared on CPU (ctx_id=-1).")

                    self._insightface = app

                    actual_providers = self.get_insightface_session_providers()
                    logger.info("InsightFace initialized session providers: %s", actual_providers)

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
        
        # 1. YOLOv8
        try:
            yolo = self.get_yolo()
            print(f"- YOLOv8 Device: {getattr(yolo, 'device', 'cpu')}")
        except Exception as e:
            print(f"- YOLOv8: Not loaded ({e})")
            logger.warning("YOLOv8 warmup skipped: %s", e)
        
        # 2. CLIP
        try:
            clip_model, _ = self.get_clip()
            print(f"- CLIP Device: {getattr(clip_model, 'device', 'cpu')}")
        except Exception as e:
            print(f"- CLIP: Not loaded ({e})")
            logger.warning("CLIP warmup skipped: %s", e)
        
        # 3. OSNet
        try:
            osnet = self.get_osnet()
            osnet_device = next(osnet.model.parameters()).device if hasattr(osnet, 'model') else self.device
            print(f"- OSNet Re-ID Device: {osnet_device}")
        except Exception as e:
            print(f"- OSNet Re-ID: Not loaded ({e})")
            logger.warning("OSNet warmup skipped: %s", e)
        
        # 4. InsightFace / ArcFace
        try:
            self._get_insightface()
            providers_map = self.get_insightface_session_providers()
            print("- InsightFace Session Execution Providers:")
            for mod_name, provs in providers_map.items():
                active_prov = provs[0] if provs else "unknown"
                print(f"  * {mod_name}: active={active_prov}, configured={provs}")
        except Exception as e:
            print(f"- InsightFace/ArcFace: Not loaded ({e})")
            logger.error("InsightFace warmup failed: %s", e)

        print("====================================================")
        logger.info("Centralized AI model warmup routine completed.")

model_manager = AIModelManager()
