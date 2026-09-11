"""
X3D-M Violence Detection Service

Provides video-level temporal violence classification and timestamp localization using the
pretrained X3D-M model (final_x3d_realtime.pt from visionlab-ai/school-violence-detection-models).

Architecture:
- Backbone: X3D-M (PyTorchVideo)
- Head: Dropout(0.3) -> Linear(2048, 2)
- Input: 16 frames, 224x224, RGB normalized with mean=(0.45, 0.45, 0.45), std=(0.225, 0.225, 0.225)
- Classes: [0: Normal / Non-violent, 1: Violent]
- Classification threshold: 0.4 (official calibrated threshold)
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

logger = logging.getLogger(__name__)


@dataclass
class ViolenceWindow:
    """Represents an individual temporal window evaluation."""
    index: int
    start_sec: float
    end_sec: float
    violent_prob: float

    @property
    def mid_sec(self) -> float:
        return (self.start_sec + self.end_sec) / 2.0


@dataclass
class ViolenceSegmentResult:
    """Represents a merged violence interval detected in the video."""
    start_time: float
    end_time: float
    duration: float
    confidence: float
    classification: str = "Violence"


@dataclass
class X3DAnalysisResult:
    """Full analysis result from the X3D-M detector."""
    is_violent: bool
    verdict: str
    overall_confidence: float
    segments: List[ViolenceSegmentResult]
    windows: List[ViolenceWindow]
    video_duration: float
    fps: float
    total_frames: int
    timings: Dict[str, float]


class ViolenceX3D(nn.Module):
    """X3D-M binary violence classification model wrapper."""

    def __init__(self, backbone: nn.Module):
        super().__init__()
        self.backbone = backbone

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # Input: (B, C, T, H, W) -> Output: (B, 2)
        return self.backbone(x)


class X3DViolenceDetector:
    """
    Singleton service managing the pretrained X3D-M violence detection model.
    Loads the model once in memory and provides temporal sliding-window analysis.
    """

    _instance: Optional["X3DViolenceDetector"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(X3DViolenceDetector, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        checkpoint_path: Optional[str] = None,
        device: Optional[str] = None,
        threshold: float = 0.4,
        num_frames: int = 16,
        frame_size: int = 224,
    ):
        if getattr(self, "_initialized", False):
            return

        self.threshold = threshold
        self.num_frames = num_frames
        self.frame_size = frame_size
        self.mean = (0.45, 0.45, 0.45)
        self.std = (0.225, 0.225, 0.225)

        # Device resolution
        if device is None:
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        else:
            self.device = torch.device(device)

        # Locate checkpoint
        if checkpoint_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            checkpoint_path = os.path.join(base_dir, "storage", "models", "x3d", "final_x3d_realtime.pt")
            if not os.path.exists(checkpoint_path):
                checkpoint_path = os.path.join("storage", "models", "x3d", "final_x3d_realtime.pt")

        self.checkpoint_path = checkpoint_path
        self.model: Optional[ViolenceX3D] = None
        self._load_model()
        self._initialized = True

    def _load_model(self) -> None:
        """Loads X3D-M architecture and attaches pretrained checkpoint weights."""
        t_start = time.time()
        logger.info(f"[X3D] Initializing X3D-M model on device: {self.device}...")

        if not os.path.exists(self.checkpoint_path):
            raise FileNotFoundError(
                f"[X3D] Checkpoint not found at: {self.checkpoint_path}. "
                "Ensure final_x3d_realtime.pt is placed in storage/models/x3d/."
            )

        try:
            # 1. Load X3D-M backbone from PyTorchVideo hubconf (offline-friendly if cached)
            hub_dir = os.path.join(torch.hub.get_dir(), "facebookresearch_pytorchvideo_main")
            if os.path.exists(hub_dir):
                bb = torch.hub.load(hub_dir, "x3d_m", source="local", pretrained=False)
            else:
                bb = torch.hub.load("facebookresearch/pytorchvideo", "x3d_m", pretrained=False)

            # 2. Configure classification head (2 classes: Normal vs Violent)
            in_features = bb.blocks[-1].proj.in_features
            bb.blocks[-1].proj = nn.Sequential(
                nn.Dropout(p=0.3),
                nn.Linear(in_features, 2)
            )

            wrapper = ViolenceX3D(bb)

            # 3. Load checkpoint state_dict
            checkpoint = torch.load(self.checkpoint_path, map_location="cpu", weights_only=False)
            if isinstance(checkpoint, dict) and "model" in checkpoint:
                state_dict = checkpoint["model"]
            else:
                state_dict = checkpoint

            missing, unexpected = wrapper.load_state_dict(state_dict, strict=True)
            if missing or unexpected:
                logger.warning(f"[X3D] Key mismatch - missing: {len(missing)}, unexpected: {len(unexpected)}")

            wrapper = wrapper.to(self.device).eval()
            self.model = wrapper
            load_time = time.time() - t_start
            logger.info(f"[X3D] Model loading completed successfully in {load_time:.3f} sec.")

        except Exception as e:
            logger.error(f"[X3D] Failed to load X3D-M model: {e}")
            raise

    def preprocess_clip(self, frames: List[np.ndarray], start_idx: int, end_idx: int) -> torch.Tensor:
        """
        Uniformly samples `num_frames` from slice [start_idx, end_idx),
        resizes to (frame_size, frame_size), normalizes to RGB, and returns (1, 3, T, H, W) tensor.
        """
        total_len = len(frames)
        end_idx = min(end_idx, total_len)
        start_idx = max(0, min(start_idx, end_idx - 1))

        indices = np.linspace(start_idx, end_idx - 1, num=self.num_frames).astype(int)
        h, w = self.frame_size, self.frame_size

        sampled = [cv2.resize(frames[i], (w, h), interpolation=cv2.INTER_LINEAR) for i in indices]
        arr = np.stack(sampled, axis=0)  # (T, H, W, 3) BGR
        arr = arr[..., ::-1].copy()      # (T, H, W, 3) RGB

        tensor = torch.from_numpy(arr).float() / 255.0
        tensor = tensor.permute(3, 0, 1, 2).contiguous()  # (C=3, T, H, W)

        mean_t = torch.tensor(self.mean, dtype=torch.float32).view(3, 1, 1, 1)
        std_t = torch.tensor(self.std, dtype=torch.float32).view(3, 1, 1, 1)
        tensor = (tensor - mean_t) / std_t

        return tensor.unsqueeze(0)  # (1, 3, T, H, W)

    def detect_violence(
        self,
        video_path: Union[str, Path],
        window_duration_sec: float = 2.0,
        stride_sec: float = 1.0,
        threshold: Optional[float] = None,
        context_margin_sec: float = 1.0,
    ) -> X3DAnalysisResult:
        """
        Executes video-level temporal violence analysis using sliding windows.

        Args:
            video_path: Path to the CCTV video file.
            window_duration_sec: Length of each temporal window in seconds (default 2.0s).
            stride_sec: Sliding stride in seconds between consecutive windows (default 1.0s).
            threshold: Probability threshold above which a window is considered violent (default 0.4).
            context_margin_sec: Additional margin added to start/end of violent segments.

        Returns:
            X3DAnalysisResult with classification, timestamps, segments, and timings.
        """
        total_start = time.time()
        thr = threshold if threshold is not None else self.threshold
        path_str = str(video_path)

        if not os.path.exists(path_str):
            raise FileNotFoundError(f"[X3D] Video not found: {path_str}")

        # 1. Read Video Frames
        t_pre = time.time()
        cap = cv2.VideoCapture(path_str)
        if not cap.isOpened():
            raise RuntimeError(f"[X3D] Could not open video container: {path_str}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        if fps <= 0:
            fps = 25.0

        raw_frames: List[np.ndarray] = []
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            raw_frames.append(frame)
        cap.release()

        n_frames = len(raw_frames)
        if n_frames == 0:
            raise RuntimeError(f"[X3D] Video contains no decodable frames: {path_str}")

        duration = n_frames / fps
        pre_time = time.time() - t_pre
        logger.info(f"[X3D] Loaded {n_frames} frames ({duration:.2f}s @ {fps:.1f} fps) in {pre_time:.3f} sec.")

        # 2. Plan Temporal Windows
        window_len_frames = max(int(round(window_duration_sec * fps)), self.num_frames)
        stride_frames = max(int(round(stride_sec * fps)), 1)

        window_starts: List[int] = []
        if n_frames <= window_len_frames:
            window_starts = [0]
        else:
            curr = 0
            while curr + self.num_frames <= n_frames:
                window_starts.append(curr)
                if curr + window_len_frames >= n_frames:
                    break
                curr += stride_frames

        # 3. Sliding Window Inference
        t_inf = time.time()
        windows: List[ViolenceWindow] = []

        with torch.no_grad():
            for idx, s_idx in enumerate(window_starts):
                e_idx = min(s_idx + window_len_frames, n_frames)
                clip_tensor = self.preprocess_clip(raw_frames, s_idx, e_idx).to(self.device)

                logits = self.model(clip_tensor)
                probs = F.softmax(logits, dim=1)[0].cpu().numpy()
                p_violent = float(probs[1])

                w_start = s_idx / fps
                w_end = e_idx / fps

                windows.append(
                    ViolenceWindow(
                        index=idx,
                        start_sec=w_start,
                        end_sec=w_end,
                        violent_prob=p_violent
                    )
                )

        inf_time = time.time() - t_inf
        logger.info(f"[X3D] Evaluated {len(windows)} temporal windows in {inf_time:.3f} sec.")

        # 4. Extract and Merge Violent Segments
        t_seg = time.time()
        violent_windows = [w for w in windows if w.violent_prob >= thr]

        segments: List[ViolenceSegmentResult] = []
        if violent_windows:
            groups: List[List[ViolenceWindow]] = []
            current_group: List[ViolenceWindow] = [violent_windows[0]]

            for w in violent_windows[1:]:
                prev_w = current_group[-1]
                if w.start_sec <= prev_w.end_sec + 0.5:
                    current_group.append(w)
                else:
                    groups.append(current_group)
                    current_group = [w]
            groups.append(current_group)

            for grp in groups:
                raw_start = grp[0].start_sec
                raw_end = grp[-1].end_sec
                max_conf = max(w.violent_prob for w in grp)

                final_start = max(0.0, raw_start - context_margin_sec)
                final_end = min(duration, raw_end + context_margin_sec)
                seg_dur = max(0.5, final_end - final_start)

                segments.append(
                    ViolenceSegmentResult(
                        start_time=round(final_start, 2),
                        end_time=round(final_end, 2),
                        duration=round(seg_dur, 2),
                        confidence=round(max_conf, 4),
                        classification="Violence"
                    )
                )

        seg_time = time.time() - t_seg
        total_time = time.time() - total_start

        is_violent = len(segments) > 0
        overall_conf = max([s.confidence for s in segments], default=0.0)
        verdict = (
            f"VIOLENCE DETECTED: {len(segments)} aggressive physical altercation segment(s) located."
            if is_violent
            else "Normal campus activity verified. No violence or aggressive physical altercations detected."
        )

        timings = {
            "model_loading_sec": 0.0,
            "video_preprocessing_sec": round(pre_time, 4),
            "violence_inference_sec": round(inf_time, 4),
            "segment_extraction_sec": round(seg_time, 4),
            "total_x3d_sec": round(total_time, 4),
        }

        logger.info(
            f"[X3D] Analysis complete: is_violent={is_violent}, segments={len(segments)}, "
            f"max_conf={overall_conf:.4f}, total_time={total_time:.3f}s"
        )

        return X3DAnalysisResult(
            is_violent=is_violent,
            verdict=verdict,
            overall_confidence=overall_conf,
            segments=segments,
            windows=windows,
            video_duration=duration,
            fps=fps,
            total_frames=n_frames,
            timings=timings
        )


def detect_video_violence(video_path: Union[str, Path], **kwargs) -> X3DAnalysisResult:
    """Convenience functional interface for X3D-M violence detection."""
    detector = X3DViolenceDetector()
    return detector.detect_violence(video_path, **kwargs)
