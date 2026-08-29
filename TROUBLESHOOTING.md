# Troubleshooting Guide

This guide covers common issues, warnings, and error cases encountered during setup, model warmups, database operations, or client actions.

---

## 1. Python Environment & Installation Mismatches

### A. Python Version Mismatches
- **Symptom**: Errors during compilation of packages, particularly C/C++ extensions.
- **Root Cause**: Installing dependencies on Python 3.13+ where wheels are not pre-built yet.
- **Resolution**: Use **Python 3.10 or 3.11**. If you must use Python 3.12, ensure Microsoft Visual C++ Build Tools (with C++ build workloads) are installed.

### B. lap / lapx package compile failure (ByteTrack Dependency)
- **Symptom**: `pip install lap` fails with `C++ compiler required` or missing `lap.h` headers.
- **Root Cause**: The standard `lap` package requires compiling a C module. ByteTrack requires this package to solve linear assignment problems.
- **Resolution**: We use `lapx` which is a drop-in replacement that includes precompiled wheels for Windows platforms. Ensure your `requirements.txt` specifies `lapx>=0.5.10` and install it.

---

## 2. AI Model Ingestion & Vector Index Issues

### A. Qdrant `cctv_embeddings` collection is empty (count = 0)
- **Symptom**: Video completes processing, but search returns 0 results.
- **Root Cause**: In-memory Qdrant instance is not persisted between restarts, or the Celery worker and FastAPI backend are writing to disjoint SQLite db / Qdrant paths.
- **Resolution**: Ensure both backend and Celery worker point to the same absolute folder path for `STORAGE_DIR`. By default, `qdrant_db` is stored under `storage/qdrant_db` which keeps it persisted on disk. 

### B. CLIP Embedding Generation Fails
- **Symptom**: Model crash when generating visual CLIP vectors for detections.
- **Root Cause**: Mismatches in CLIP output structures (e.g. accessing `BaseModelOutputWithPooling` outputs on older transformers versions).
- **Resolution**: The project uses `transformers>=4.38.0` where CLIP returns output structures containing both `image_embeds` and `text_embeds`. Keep the dependencies updated as declared in `requirements.txt`.

### C. CUDA / GPU Out of Memory (OOM)
- **Symptom**: CUDA out of memory errors when processing large videos.
- **Root Cause**: Multiple models loaded in GPU VRAM (YOLOv8 + CLIP + OSNet + ArcFace) running batches.
- **Resolution**: Ensure `torch.cuda.empty_cache()` is triggered after frames processing. If VRAM is below 4GB, configure the pipeline target FPS lower (e.g., `target_fps=2.0` or `3.0`) or run in CPU fallback mode by setting environment flags.

---

## 3. Web Sockets & Authentication Errors

### A. WebSocket double accept or connection closed
- **Symptom**: WebSocket connection is established but immediately terminates.
- **Root Cause**: Multiple connection accepts in FastAPI routes, or auth token validation throws an exception and closes the channel.
- **Resolution**: Avoid double calls to `await websocket.accept()`. Validate token parameters before accepting the handshakes.

### B. bcrypt/passlib package runtime warnings
- **Symptom**: `TypeError: 'NoneType' object is not callable` in `passlib.hash.bcrypt` under Python 3.12+.
- **Root Cause**: Passlib bcrypt adapter is incompatible with newer versions of `bcrypt` library (4.1.0+).
- **Resolution**: Install `bcrypt==4.0.1` and `passlib[bcrypt]==1.7.4`. Alternatively, the password verification routines in `backend/app/core/security.py` are patched to use the standard `bcrypt` hashing module directly rather than calling passlib adapters.
