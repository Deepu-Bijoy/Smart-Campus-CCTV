import os
import sys
import time
import psutil
import torch
import cv2
import numpy as np

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.core.model_manager import model_manager
from app.pipeline.x3d_violence_detector import X3DViolenceDetector

def get_mem():
    vm = psutil.virtual_memory()
    gpu_mem = torch.cuda.memory_allocated() / (1024**2) if torch.cuda.is_available() else 0
    gpu_reserved = torch.cuda.memory_reserved() / (1024**2) if torch.cuda.is_available() else 0
    return {
        "ram_used_gb": (vm.total - vm.available) / (1024**3),
        "ram_percent": vm.percent,
        "gpu_alloc_mb": gpu_mem,
        "gpu_reserved_mb": gpu_reserved
    }

def profile_components():
    print("=" * 65)
    print("STEP 1: CCTV PIPELINE BOTTLENECK PROFILING")
    print("=" * 65)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Device: {device}")
    if torch.cuda.is_available():
        print(f"GPU: {torch.cuda.get_device_name(0)}, Total VRAM: {torch.cuda.get_device_properties(0).total_memory / (1024**3):.2f} GB")
    mem_init = get_mem()
    print(f"Initial RAM used: {mem_init['ram_used_gb']:.2f} GB ({mem_init['ram_percent']}%), GPU VRAM: {mem_init['gpu_alloc_mb']:.1f} MB")

    test_video_21min = os.path.join(settings.STORAGE_DIR, "07673e09-e558-46fe-8cc5-34536231ea8f.mp4")
    short_video = os.path.join(settings.STORAGE_DIR, "test_debug_media", "x3d_fight_event.mp4")
    video_to_use = test_video_21min if os.path.exists(test_video_21min) else short_video

    print(f"Target Video: {video_to_use}")
    cap = cv2.VideoCapture(video_to_use)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    fc = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    cap.release()
    dur = fc / fps if fps > 0 else 0
    print(f"Video Stats: {dur:.2f}s ({dur/60:.2f}m), {fc} frames @ {fps} FPS, {w}x{h}")
    raw_size_gb = (fc * w * h * 3) / (1024**3)
    print(f"Calculated Uncompressed Raw Frame Size: {raw_size_gb:.2f} GB in RAM")

    # 1. Profile Video Decoding: Frame reading throughput
    print("\n[1] Profiling Video Decoding (first 500 frames)...")
    t0 = time.time()
    cap = cv2.VideoCapture(video_to_use)
    count = 0
    while count < 500:
        ret, frame = cap.read()
        if not ret: break
        count += 1
    cap.release()
    decode_time = time.time() - t0
    decode_fps = count / decode_time if decode_time > 0 else 0
    print(f"Decoded {count} frames in {decode_time:.3f}s -> {decode_fps:.1f} FPS")

    # 2. Profile X3D Model & Inference
    print("\n[2] Profiling X3D-M Violence Detection...")
    t0 = time.time()
    detector = X3DViolenceDetector()
    t_load = time.time() - t0
    print(f"X3D Model Load Time: {t_load:.3f}s (Device: {detector.device})")

    # Benchmark X3D forward pass: Batch size 1 vs Batch size 4, 8, 16 in FP32 and FP16
    input_shape = (1, 3, 16, 224, 224)
    dummy_input_fp32 = torch.randn(input_shape, dtype=torch.float32, device=detector.device)
    
    # Warmup
    with torch.no_grad():
        for _ in range(5):
            _ = detector.model(dummy_input_fp32)
    if torch.cuda.is_available(): torch.cuda.synchronize()

    # Time FP32 Batch size 1 (Current implementation)
    iters = 20
    t0 = time.time()
    with torch.no_grad():
        for _ in range(iters):
            _ = detector.model(dummy_input_fp32)
        if torch.cuda.is_available(): torch.cuda.synchronize()
    fp32_b1_time = (time.time() - t0) / iters
    print(f"X3D FP32 Batch 1: {fp32_b1_time*1000:.2f} ms per window ({1.0/fp32_b1_time:.1f} windows/sec)")

    # Time FP16 Batch size 1
    if torch.cuda.is_available():
        detector.model.half()
        dummy_input_fp16 = dummy_input_fp32.half()
        with torch.no_grad():
            for _ in range(5): _ = detector.model(dummy_input_fp16)
            torch.cuda.synchronize()
            t0 = time.time()
            for _ in range(iters):
                _ = detector.model(dummy_input_fp16)
            torch.cuda.synchronize()
        fp16_b1_time = (time.time() - t0) / iters
        print(f"X3D FP16 Batch 1: {fp16_b1_time*1000:.2f} ms per window ({1.0/fp16_b1_time:.1f} windows/sec)")

        # Benchmark FP16 Batched (Batch size 8)
        dummy_b8_fp16 = torch.randn((8, 3, 16, 224, 224), dtype=torch.float16, device=detector.device)
        with torch.no_grad():
            for _ in range(5): _ = detector.model(dummy_b8_fp16)
            torch.cuda.synchronize()
            t0 = time.time()
            for _ in range(iters):
                _ = detector.model(dummy_b8_fp16)
            torch.cuda.synchronize()
        fp16_b8_time = (time.time() - t0) / (iters * 8)
        print(f"X3D FP16 Batch 8: {fp16_b8_time*1000:.2f} ms per window ({1.0/fp16_b8_time:.1f} windows/sec)")
        print(f"Speedup from Batching & FP16: {fp32_b1_time / fp16_b8_time:.2f}x faster inference!")

        # Reset model to float32
        detector.model.float()

    # 3. Profile YOLOv8 & ByteTrack
    print("\n[3] Profiling YOLOv8 & ByteTrack...")
    yolo = model_manager.get_yolo("yolov8n.pt")
    dummy_frame = np.zeros((576, 720, 3), dtype=np.uint8)
    
    # Warmup
    _ = yolo.predict(dummy_frame, device=device, verbose=False)
    
    t0 = time.time()
    for _ in range(20):
        _ = yolo.predict(dummy_frame, device=device, verbose=False)
    yolo_fp32_time = (time.time() - t0) / 20
    print(f"YOLOv8 FP32 Frame: {yolo_fp32_time*1000:.2f} ms ({1.0/yolo_fp32_time:.1f} FPS)")

    if torch.cuda.is_available():
        t0 = time.time()
        for _ in range(20):
            _ = yolo.predict(dummy_frame, device=device, half=True, verbose=False)
        yolo_fp16_time = (time.time() - t0) / 20
        print(f"YOLOv8 FP16 Frame: {yolo_fp16_time*1000:.2f} ms ({1.0/yolo_fp16_time:.1f} FPS)")

    # 4. Profile ByteTrack
    from app.pipeline.tracker import ByteTrackTracker
    tracker = ByteTrackTracker()
    from app.pipeline.detector import YOLOv8Detector
    y_det = YOLOv8Detector()
    t0 = time.time()
    for _ in range(20):
        _ = tracker.track_frame(y_det, dummy_frame, persist=True)
    bt_time = (time.time() - t0) / 20
    print(f"YOLO+ByteTrack per frame: {bt_time*1000:.2f} ms ({1.0/bt_time:.1f} FPS)")

    # 5. Profile ArcFace / InsightFace
    print("\n[4] Profiling InsightFace / ArcFace...")
    from app.pipeline.face_engine import FaceEnrollmentEngine
    face_engine = FaceEnrollmentEngine()
    dummy_crop = np.zeros((120, 100, 3), dtype=np.uint8)
    if face_engine.model is not None:
        t0 = time.time()
        for _ in range(10):
            _ = face_engine.model.get(dummy_crop)
        face_time = (time.time() - t0) / 10
        print(f"InsightFace per crop: {face_time*1000:.2f} ms ({1.0/face_time:.1f} crops/sec)")
    else:
        print("InsightFace model is None")

    print("\n" + "=" * 65)
    print("PROFILING COMPLETED")
    print("=" * 65)

if __name__ == "__main__":
    profile_components()
