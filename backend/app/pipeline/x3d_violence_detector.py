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
            self.mean_t = torch.tensor(self.mean, dtype=torch.float32, device=self.device).view(1, 3, 1, 1, 1)
            self.std_t = torch.tensor(self.std, dtype=torch.float32, device=self.device).view(1, 3, 1, 1, 1)
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
        batch_size: int = 16,
        progress_callback: Optional[Callable[[int, int], None]] = None,
    ) -> X3DAnalysisResult:
        """
        Executes bounded-memory streaming video-level temporal violence analysis using sliding windows.

        Args:
            video_path: Path to the CCTV video file.
            window_duration_sec: Length of each temporal window in seconds (default 2.0s).
            stride_sec: Sliding stride in seconds between consecutive windows (default 1.0s).
            threshold: Probability threshold above which a window is considered violent (default 0.4).
            context_margin_sec: Additional margin added to start/end of violent segments.
            batch_size: Batch size of temporal windows evaluated simultaneously on GPU (default 16).
            progress_callback: Optional callback invoked with (completed_windows, total_windows).

        Returns:
            X3DAnalysisResult with classification, timestamps, segments, and timings.
        """
        total_start = time.time()
        thr = threshold if threshold is not None else self.threshold
        path_str = str(video_path)

        if not os.path.exists(path_str):
            raise FileNotFoundError(f"[X3D] Video not found: {path_str}")

        cap = cv2.VideoCapture(path_str)
        if not cap.isOpened():
            raise RuntimeError(f"[X3D] Could not open video container: {path_str}")

        fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
        if fps <= 0:
            fps = 25.0

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        # Plan Temporal Windows
        window_len_frames = max(int(round(window_duration_sec * fps)), self.num_frames)
        stride_frames = max(int(round(stride_sec * fps)), 1)

        window_plan: List[Tuple[int, int]] = []
        if total_frames > 0:
            if total_frames <= window_len_frames:
                window_plan.append((0, total_frames))
            else:
                curr = 0
                while curr + self.num_frames <= total_frames:
                    e_idx = min(curr + window_len_frames, total_frames)
                    window_plan.append((curr, e_idx))
                    if curr + window_len_frames >= total_frames:
                        break
                    curr += stride_frames

        total_planned_windows = len(window_plan)
        logger.info(
            f"[X3D] Initializing streaming inference for {path_str} "
            f"({total_frames} frames @ {fps:.1f} fps, {total_planned_windows} planned windows, "
            f"batch_size={batch_size}, bounded buffer)."
        )

        # Pre-resolved normalization tensors
        if not hasattr(self, "mean_t") or self.mean_t is None or self.mean_t.device != self.device:
            self.mean_t = torch.tensor(self.mean, dtype=torch.float32, device=self.device).view(1, 3, 1, 1, 1)
            self.std_t = torch.tensor(self.std, dtype=torch.float32, device=self.device).view(1, 3, 1, 1, 1)

        t_pre_total = 0.0
        t_inf_total = 0.0

        buffer: Dict[int, np.ndarray] = {}
        windows: List[ViolenceWindow] = []
        batch_tensors: List[torch.Tensor] = []
        batch_metadata: List[Tuple[int, float, float]] = []

        curr_frame_idx = 0
        next_window_idx = 0
        h, w = self.frame_size, self.frame_size
        use_amp = self.device.type == "cuda"

        def _flush_batch() -> None:
            nonlocal batch_tensors, batch_metadata, windows, t_inf_total
            if not batch_tensors:
                return

            t_inf_start = time.time()
            batch_input = torch.cat(batch_tensors, dim=0)

            with torch.no_grad():
                if use_amp:
                    with torch.autocast(device_type="cuda", dtype=torch.float16):
                        logits = self.model(batch_input)
                else:
                    logits = self.model(batch_input)
                probs = F.softmax(logits.float(), dim=1)[:, 1].cpu().numpy()

            for (w_idx, w_start, w_end), p_violent in zip(batch_metadata, probs):
                windows.append(
                    ViolenceWindow(
                        index=w_idx,
                        start_sec=w_start,
                        end_sec=w_end,
                        violent_prob=float(p_violent)
                    )
                )

            t_inf_total += (time.time() - t_inf_start)
            batch_tensors = []
            batch_metadata = []

            if progress_callback and total_planned_windows > 0:
                try:
                    progress_callback(len(windows), total_planned_windows)
                except Exception as cb_err:
                    logger.debug(f"[X3D] Progress callback error: {cb_err}")

        # Streaming sliding-buffer reading loop
        t_decode_start = time.time()
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            buffer[curr_frame_idx] = frame

            # If total_frames was unknown at start, plan window dynamically
            if total_planned_windows == 0:
                s_cand = next_window_idx * stride_frames
                if curr_frame_idx + 1 >= s_cand + window_len_frames:
                    window_plan.append((s_cand, s_cand + window_len_frames))

            # Assemble complete windows from buffer
            while next_window_idx < len(window_plan):
                s_idx, e_idx = window_plan[next_window_idx]
                if curr_frame_idx + 1 >= e_idx:
                    t_pre_start = time.time()
                    indices = np.linspace(s_idx, e_idx - 1, num=self.num_frames).astype(int)
                    sampled = [cv2.resize(buffer[i], (w, h), interpolation=cv2.INTER_LINEAR) for i in indices]
                    arr = np.stack(sampled, axis=0)
                    arr = arr[..., ::-1].copy()

                    t_clip = torch.from_numpy(arr).to(self.device).float() / 255.0
                    t_clip = t_clip.permute(3, 0, 1, 2).contiguous().unsqueeze(0)
                    t_clip = (t_clip - self.mean_t) / self.std_t
                    t_pre_total += (time.time() - t_pre_start)

                    batch_tensors.append(t_clip)
                    batch_metadata.append((next_window_idx, s_idx / fps, e_idx / fps))
                    next_window_idx += 1

                    if len(batch_tensors) >= batch_size:
                        _flush_batch()
                else:
                    break

            # Evict past frames from buffer to keep memory strictly bounded
            if next_window_idx < len(window_plan):
                min_needed_frame = window_plan[next_window_idx][0]
                evict_keys = [k for k in buffer if k < min_needed_frame]
                for k in evict_keys:
                    del buffer[k]

            curr_frame_idx += 1

        cap.release()

        # Handle final partial window at EOF if video was shorter or dynamically planned
        if total_planned_windows == 0 and curr_frame_idx >= self.num_frames:
            s_cand = next_window_idx * stride_frames
            if s_cand + self.num_frames <= curr_frame_idx:
                e_cand = curr_frame_idx
                indices = np.linspace(s_cand, e_cand - 1, num=self.num_frames).astype(int)
                sampled = [cv2.resize(buffer[i], (w, h), interpolation=cv2.INTER_LINEAR) for i in indices]
                arr = np.stack(sampled, axis=0)[..., ::-1].copy()
                t_clip = torch.from_numpy(arr).to(self.device).float() / 255.0
                t_clip = t_clip.permute(3, 0, 1, 2).contiguous().unsqueeze(0)
                t_clip = (t_clip - self.mean_t) / self.std_t
                batch_tensors.append(t_clip)
                batch_metadata.append((next_window_idx, s_cand / fps, e_cand / fps))
                next_window_idx += 1

        # Process any remaining windows in the final batch
        _flush_batch()
        buffer.clear()

        n_frames = curr_frame_idx
        if n_frames == 0 or len(windows) == 0:
            raise RuntimeError(f"[X3D] Video contains no decodable frames or windows: {path_str}")

        duration = n_frames / fps
        pre_time = time.time() - t_decode_start

        logger.info(
            f"[X3D] Streaming evaluation complete: {len(windows)} windows from {n_frames} frames "
            f"({duration:.2f}s @ {fps:.1f} fps) in {pre_time:.3f}s total (Inference: {t_inf_total:.3f}s)."
        )

        # Extract and Merge Violent Segments
        t_seg = time.time()
        violent_windows = [w for w in windows if w.violent_prob >= thr]

        segments: List[ViolenceSegmentResult] = []
        if violent_windows:
            groups: List[List[ViolenceWindow]] = []
            current_group: List[ViolenceWindow] = [violent_windows[0]]

            for w_item in violent_windows[1:]:
                prev_w = current_group[-1]
                if w_item.start_sec <= prev_w.end_sec + 0.5:
                    current_group.append(w_item)
                else:
                    groups.append(current_group)
                    current_group = [w_item]
            groups.append(current_group)

            for grp in groups:
                raw_start = grp[0].start_sec
                raw_end = grp[-1].end_sec
                max_conf = max(w_item.violent_prob for w_item in grp)

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
            "video_preprocessing_sec": round(t_pre_total, 4),
            "violence_inference_sec": round(t_inf_total, 4),
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
