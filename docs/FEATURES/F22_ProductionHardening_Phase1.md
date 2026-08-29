# F22: Production Hardening Phase 1

## Purpose
This document logs the implementations for **Production Hardening Phase 1**: resolving GPU Memory Over-allocation and securing the WebSocket Alert channel.

---

## 1. Centralized AI Model Manager
Loads deep learning weights in a thread-safe singleton cache:
- **Models Coordinated**: YOLOv8, InsightFace, ArcFace, OSNet, and CLIP.
- **Warmup Hooks**: FastAPI `startup` triggers preloading all models onto the active device context (CUDA or CPU fallback).
- **Exposed Methods**:
  * `get_yolo()`
  * `get_clip()`
  * `get_osnet()`
  * `get_arcface()`
  * `get_face_detector()`

---

## 2. Celery Routing Segregations
Task distributions are segmented into separate queues:
- `gpu_queue`: Reserved for model inference execution tasks (`process_video`). Runs with concurrency limit `1` to avoid VRAM over-allocation.
- `cpu_queue`: Offloads non-inference execution tasks (Reports compilation, Notifications routing, Timeline statistics updates).

---

## 3. Secure WebSocket Authentication
- **Requirements**: Incoming handshakes must provide a valid operator/admin JWT token via query parameter (`token`) or header (`Authorization`).
- **Additional Security Controls**:
  * **Rate Limiting**: Limits client IP reconnects (maximum 5 attempts per 10 seconds).
  * **Heartbeat Ping-Pong**: Exposes PING-PONG heartbeat frames.
  * **Cleanup**: Automatically cleans up dead connections during broadcasts.
