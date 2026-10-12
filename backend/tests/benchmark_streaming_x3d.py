import os
import sys
import time
import cv2
import torch
import torch.nn.functional as F
import numpy as np
from collections import deque
from typing import List, Optional, Callable

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.pipeline.x3d_violence_detector import (
    X3DViolenceDetector,
    ViolenceWindow,
    ViolenceSegmentResult,
    X3DAnalysisResult
)

def benchmark_streaming_detector(video_path: str, batch_size: int = 16, use_amp: bool = True):
    detector = X3DViolenceDetector()
    cap = cv2.VideoCapture(video_path)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    if fps <= 0: fps = 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    
    window_duration_sec = 2.0
    stride_sec = 1.0
    thr = detector.threshold
    context_margin_sec = 1.0
    
    window_len_frames = max(int(round(window_duration_sec * fps)), detector.num_frames)
    stride_frames = max(int(round(stride_sec * fps)), 1)
    
    # Pre-plan window ranges (start_frame, end_frame)
    window_plan = []
    if total_frames > 0 and total_frames <= window_len_frames:
        window_plan.append((0, total_frames))
    else:
        curr = 0
        # If total_frames unknown, will plan dynamically
        if total_frames > 0:
            while curr + detector.num_frames <= total_frames:
                e_idx = min(curr + window_len_frames, total_frames)
                window_plan.append((curr, e_idx))
                if curr + window_len_frames >= total_frames:
                    break
                curr += stride_frames

    total_expected_windows = len(window_plan)
    print(f"Total planned windows: {total_expected_windows}, Frame len per window: {window_len_frames}, Stride: {stride_frames}")

    # Streaming bounded buffer execution
    t_start = time.time()
    buffer = {}  # frame_idx -> frame
    windows = []
    batch_tensors = []
    batch_metadata = []

    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    curr_frame_idx = 0
    next_window_idx = 0
    
    device = detector.device
    num_frames = detector.num_frames
    frame_size = detector.frame_size
    mean_t = torch.tensor(detector.mean, dtype=torch.float32, device=device).view(1, 3, 1, 1, 1)
    std_t = torch.tensor(detector.std, dtype=torch.float32, device=device).view(1, 3, 1, 1, 1)

    def process_batch():
        nonlocal batch_tensors, batch_metadata, windows
        if not batch_tensors:
            return
        
        batch_input = torch.cat(batch_tensors, dim=0)
        with torch.no_grad():
            if use_amp and device.type == "cuda":
                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    logits = detector.model(batch_input)
            else:
                logits = detector.model(batch_input)
            probs = F.softmax(logits.float(), dim=1)[:, 1].cpu().numpy()

        for (idx, w_start, w_end), p_violent in zip(batch_metadata, probs):
            windows.append(
                ViolenceWindow(
                    index=idx,
                    start_sec=w_start,
                    end_sec=w_end,
                    violent_prob=float(p_violent)
                )
            )
        batch_tensors = []
        batch_metadata = []

    min_needed_frame = 0
    
    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            break
        buffer[curr_frame_idx] = frame

        # Check if windows can be built
        while next_window_idx < len(window_plan):
            s_idx, e_idx = window_plan[next_window_idx]
            if curr_frame_idx + 1 >= e_idx:
                # Window is fully within buffer!
                # Extract 16 frames
                sample_indices = np.linspace(s_idx, e_idx - 1, num=num_frames).astype(int)
                sampled_frames = [buffer[si] for si in sample_indices]
                
                # Resize and tensorize
                resized = [cv2.resize(f, (frame_size, frame_size), interpolation=cv2.INTER_LINEAR) for f in sampled_frames]
                arr = np.stack(resized, axis=0) # (T, H, W, 3) BGR
                arr = arr[..., ::-1].copy()     # (T, H, W, 3) RGB
                t = torch.from_numpy(arr).to(device).float() / 255.0
                t = t.permute(3, 0, 1, 2).contiguous().unsqueeze(0) # (1, 3, T, H, W)
                t = (t - mean_t) / std_t

                batch_tensors.append(t)
                batch_metadata.append((next_window_idx, s_idx / fps, e_idx / fps))
                next_window_idx += 1

                if len(batch_tensors) >= batch_size:
                    process_batch()
            else:
                break

        # Evict old frames that are no longer needed by any remaining windows
        if next_window_idx < len(window_plan):
            min_needed_frame = window_plan[next_window_idx][0]
            # Prune buffer
            to_remove = [k for k in buffer if k < min_needed_frame]
            for k in to_remove:
                del buffer[k]

        curr_frame_idx += 1

    # Remaining batch
    process_batch()
    cap.release()

    total_time = time.time() - t_start
    print(f"Evaluated {len(windows)} windows in {total_time:.3f}s (FPS: {curr_frame_idx/total_time:.1f})")

    # Segment extraction
    violent_windows = [w for w in windows if w.violent_prob >= thr]
    segments = []
    duration = curr_frame_idx / fps if fps > 0 else 0.0

    if violent_windows:
        groups = []
        current_group = [violent_windows[0]]
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

    return windows, segments, total_time

if __name__ == "__main__":
    test_vid = "storage/920f6306-6f9c-4b4a-a73a-cc073328a3c0.mp4"
    print(f"Testing on {test_vid}...")
    windows, segs, t = benchmark_streaming_detector(test_vid, batch_size=16, use_amp=True)
    print(f"Segments: {len(segs)}")
    for s in segs:
        print(f"  Segment: {s.start_time} - {s.end_time}, Conf: {s.confidence}")
