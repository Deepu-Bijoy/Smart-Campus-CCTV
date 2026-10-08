# PHASE 5 — FAILURE, RESILIENCE & ERROR-HANDLING VALIDATION REPORT

**Project:** AI-Powered Smart CCTV Investigation System  
**Workspace:** `C:\Users\Asus\OneDrive\Desktop\AI-Powered Smart CCTV Investigation System`  
**Phase:** Phase 5 — Failure, Resilience & Error-Handling Validation  
**Date:** October 7, 2026  
**Status:** COMPLETE & LOCKED  
**Final Resilience Verdict:** **`RESILIENCE VERIFIED WITH LIMITATIONS`**  
**Remediation Record:** Remediated and verified in [`docs/RESILIENCE_REMEDIATION.md`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/RESILIENCE_REMEDIATION.md) (Phase 5A Verdict: **`RESILIENCE VERIFIED`**)

---

## 1. Executive Summary

Phase 5 performed a rigorous, empirical validation of the existing **AI-Powered Smart CCTV Investigation System** under failure, invalid input, resource exhaustion, missing dependency, transaction abort, and concurrency scenarios.

In strict adherence to the project guidelines:
- **No source code was modified to silently fix issues**; all behaviors were measured as-is.
- **X3D-M architecture, weights, thresholds, and violence logic remained completely untouched.**
- **No real project data, databases, or surveillance footage were deleted or corrupted.**
- All validation tests were codified in a dedicated test suite: [`backend/tests/resilience/test_resilience_validation.py`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/tests/resilience/test_resilience_validation.py).
- **Test Suite Results:** 43 tests collected, **43 PASSED**, 0 failed, 0 skipped, 0 blocked.

---

## 2. Baseline Environment Status (Step 1)

Before commencing stress and failure tests, the active operating environment was audited and recorded:

| Component | Target / Specification | Measured State | Operational Status |
| :--- | :--- | :--- | :--- |
| **Python** | 3.11.x | 3.11.15 (64-bit AMD64) | Active / Healthy |
| **FastAPI** | >= 0.100.0 | 0.141.1 | Active / Healthy |
| **SQLAlchemy** | 2.x | 2.1.0 | Active / Healthy |
| **PyTorch** | 2.x with CUDA | 2.6.0+cu124 | Active / Healthy |
| **CUDA / GPU** | NVIDIA RTX Series | NVIDIA GeForce RTX 3050 Laptop GPU | Active / Compute Capable |
| **FFmpeg / FFprobe** | Binary available in PATH | `C:\Users\Asus\.local\bin\ffmpeg.EXE`, `ffprobe.EXE` | Active / Healthy |
| **PostgreSQL** | Port 5432 (Docker) | Up 7+ hours (healthy) (`pro-postgres`) | Running |
| **SQLite Fallback** | `storage/cctv.db` | Configured active via `DB_FALLBACK_SQLITE=true` | Primary Active Backend |
| **Redis** | Port 6379 (Docker) | Up 7+ hours (healthy) (`pro-redis`) | Running |
| **Celery** | Worker / Broker | `CELERY_ALWAYS_EAGER=true` (memory broker) | Eager In-Process Execution |
| **Qdrant** | Port 6333 (Docker) | Up 7+ hours (healthy) (`pro-qdrant`) | Running |
| **Qdrant Mode** | In-Memory / Local Disk | `QDRANT_IN_MEMORY=true` (`storage/qdrant_db`) | Local Disk Persistence Active |
| **Backend Server** | Uvicorn on 0.0.0.0:8000 | Port 8000 listening, handling requests | Active / Healthy |
| **Frontend Server** | Vite on localhost:5173 | Port 5173 listening, SPA active | Active / Healthy |

---

## 3. Invalid Video Inputs (Step 2)

We probed both the Violence Ingestion (`/api/v1/violence/upload`) and General Surveillance Ingestion (`/api/v1/videos/upload`) pipelines against 11 safe, synthetic invalid video formats:

| Test Input Scenario | Target Endpoint | Expected Behavior | Actual Behavior | HTTP Code | Cleanup Verified |
| :--- | :--- | :--- | :--- | :---: | :---: |
| **1. Zero-byte File** | `/violence/upload` | Reject with 400 Bad Request | Rejected: `"Uploaded video file is empty (0 bytes)."` | **400** | Yes (deleted from disk) |
| **2. Zero-byte File** | `/videos/upload` | Handle safely without crash | Saved with `duration=0.0`, `file_size=0`; metadata fallback | **201** | Saved to DB/disk |
| **3. Corrupted MP4 Header** | `/violence/upload` | Reject with 400 Bad Request | Rejected: `"Corrupted or invalid video stream. OpenCV could not open container."` | **400** | Yes (deleted from disk) |
| **4. Truncated MP4 Box** | `/violence/upload` | Reject with 400 Bad Request | Rejected: `"Corrupted or invalid video stream. OpenCV could not open container."` | **400** | Yes (deleted from disk) |
| **5. Fake Container (Text)** | `/violence/upload` | Reject with 400 Bad Request | Rejected: `"Corrupted or invalid video stream. OpenCV could not open container."` | **400** | Yes (deleted from disk) |
| **6. Unsupported Extension (.exe)** | `/violence/upload` | Reject with 400 Bad Request | Rejected: `"Unsupported video format '.exe'."` | **400** | Yes (rejected before write) |
| **7. Oversized File (>100MB)** | `/violence/upload` | Reject with 413 Payload Too Large | Rejected: `"Video upload size exceeds 100MB limit."` | **413** | Yes (deleted from disk) |
| **8. Extremely Short (2 frames)** | `/violence/upload` | Accept and extract duration | Accepted: duration = 0.08s, fps = 25.0 | **201** | Saved cleanly |
| **9. Fewer than 16 Frames (5 frames)** | `X3DViolenceDetector` | Evaluate without crash | Interpolates linspace across 5 frames into 16 temporal slots; classification completes | **N/A** | In-memory safe |
| **10. Unusual FPS (0.5 FPS)** | `/violence/upload` | Process without div-by-zero | Accepted: duration = 6.0s, fps = 0.5; extracts 3 frames | **201** | Saved cleanly |
| **11. Zero/Negative FPS** | `VideoReader.read_frames` | Abort frame generator safely | Logs error `"Invalid original FPS"` and yields 0 frames without throwing unhandled exception | **N/A** | OpenCV released |

---

## 4. Missing Files & Disappearing Resources (Step 3)

We tested system behavior when referenced disk files, records, or models disappear:

| Scenario | Component / Endpoint | Expected Behavior | Actual Behavior | Result |
| :--- | :--- | :--- | :--- | :---: |
| **Missing Video ID** | `POST /violence/analyze` | 404 Not Found | Returns 404: `"Video with ID ... not found."` | **PASS** |
| **Missing Video Status** | `GET /violence/status/{id}` | 404 Not Found | Returns 404: `"Video not found"` | **PASS** |
| **Missing Camera** | `GET /cameras/{id}` | 404 Not Found | Returns 404: `"Camera not found"` | **PASS** |
| **Missing Incident** | `GET /investigations/incidents/{id}` | 404 Not Found | Returns 404: `"Incident not found"` | **PASS** |
| **Missing Student** | `GET /students/{id}` | 404 Not Found | Returns 404: `"Student not found"` | **PASS** |
| **Missing Evidence File** | `GET /storage/evidence/{file}` | 404 Not Found | Returns 404: `"Requested file not found"` | **PASS** |
| **Missing Report File** | `GET /reports/download/{id}` | 404 Not Found | Returns 404: `"Report not found"` | **PASS** |
| **Missing X3D Weight Checkpoint** | `X3DViolenceDetector._load_model` | Raise `FileNotFoundError` | Raises `FileNotFoundError: [X3D] Checkpoint not found at: ...` | **PASS** |

---

## 5. AI & Model Failure Handling (Step 4)

We simulated inference exceptions, out-of-memory errors, and corrupted inputs across the computer vision engines:

1. **X3D-M Inference Exception:**
   - When an unhandled CUDA runtime error occurs in `X3DViolenceDetector.detect_violence` during `POST /violence/analyze`, FastAPI returns HTTP 500 Internal Server Error.
   - *Limitation Identified:* The endpoint updates `target_video.status = "processing"` prior to calling `detect_violence()`. Because there is no `try...except` block catching model crashes in `/violence/analyze`, the video record remains stuck in `status="processing"` in the database.
2. **Face Recognition on Missing Crop:**
   - `StudentIdentifier.identify_face_in_crop("nonexistent_path.jpg")` safely returns `None` without raising unhandled exceptions or crashing the worker.
3. **YOLOv8 Inference Failure:**
   - When `model` throws an exception during `detect_batch()`, the exception is propagated to the orchestrator caller.
4. **CLIP Embedder with Empty Array:**
   - `CLIPEmbedder.embed_image(empty_tensor)` detects invalid dimensions and raises a controlled exception rather than producing corrupted NaN vectors.

---

## 6. Database Failure Handling & SQLite Column Affinity (Step 5)

### Database Resilience Findings
1. **Transaction Rollback on Constraint Violation:**
   - Attempting to insert a duplicate unique email (`admin@resilience.audit`) properly raises `sqlalchemy.exc.IntegrityError`.
   - The session safely executes `await db.rollback()`, ensuring no partial or corrupted records are committed.
2. **Database Connection Outage:**
   - When database sessions fail during an API request (e.g. pool exhaustion), the endpoint catches the transaction exception, rolls back, and returns HTTP 500.
3. **Critical Finding: SQLite Dynamic Column Affinity on UUIDs (SEC/DATA-01):**
   - In SQLite fallback mode, SQLAlchemy maps `postgresql.UUID(as_uuid=True)` to a column without native UUID affinity.
   - If a UUID consists *only* of numeric digits and hyphens (e.g. `11111111-1111-1111-1111-111111111111`), SQLite coerces it into a floating point number in scientific notation (`1.1111111111111112e+31`).
   - When SQLAlchemy subsequently deserializes the column into a UUID, it calls `.replace("-", "")`, which triggers `AttributeError: 'float' object has no attribute 'replace'` on all subsequent queries.
   - UUIDs containing hexadecimal alphabetic characters (e.g., `'a'`-`'f'`) are stored as `text` and deserialize properly.

---

## 7. Redis & Celery Failure Handling (Step 6)

1. **Permanent Error Handling in Celery:**
   - In `backend/app/tasks/video_tasks.py`, `is_permanent_error` explicitly classifies `FileNotFoundError`, `ValueError`, `ModuleNotFoundError`, and `ImportError` as permanent failures.
   - When a permanent error occurs, the task **never retries**, sets `video.status = "failed"`, `stage = "Failed"`, and writes `error_message` into the database.
2. **Broker Enqueue Outage:**
   - In `/videos/upload`, if `process_video.delay()` fails (e.g. Redis unavailable), the handler catches `Exception`, marks `video.status = "failed"`, and sets `video.current_stage = "Queue Failure"`.

---

## 8. Qdrant Vector Store Failure (Step 7)

1. **Vector Upsert Outage:**
   - If the Qdrant cluster drops during `upsert_vectors()`, `QdrantVectorStore` catches `Exception`, logs the full stack trace, and raises `ConnectionError`.
   - In `orchestrator.py` Stage 7, Qdrant exceptions are caught in a `try...except` block so database metadata persistence completes even if vector indexing fails.
2. **Search API Graceful Degradation:**
   - When Qdrant is unreachable during a natural language query, `POST /api/v1/search` catches the retrieval error and returns HTTP 500 with `"Failed to execute search query: ..."`.

---

## 9. Duplicate & Concurrent Processing (Step 8)

1. **Identical Video Uploaded Twice:**
   - Uploading the identical byte stream twice generates two completely independent `video_id` UUIDs and disk files (`{uuid}.mp4`).
   - The system does not suffer file collisions or race conditions during ingest.
2. **Repeated Report Generation (Idempotency Limitation):**
   - Requesting `POST /api/v1/reports/generate` multiple times for the same incident creates duplicate `Report` rows in the database with different IDs rather than returning an existing report.

---

## 10. Partial Pipeline Failure (Step 9)

We traced the 10-stage execution pipeline:
$$\text{Video} \to \text{Validation} \to \text{Frame Extraction} \to \text{YOLO} \to \text{ByteTrack} \to \text{X3D-M} \to \text{Embeddings} \to \text{Evidence} \to \text{Incident} \to \text{Report}$$

1. **Stage 1 (Validation Failure):**
   - If the video file is missing on disk, `_stage_validate_video` raises `FileNotFoundError`, stopping the pipeline immediately.
2. **Frame Extraction Failure on 0 Decodable Frames:**
   - If a video container is valid but has 0 frames or 0 FPS, `VideoReader` yields 0 frames.
   - *Limitation Identified:* In `orchestrator.execute()`, 0 frames result in 0 tracks, 0 detections, and 0 vector points, but Stage 8 completes and marks `status="completed"`. The pipeline silently marks empty/unreadable videos as successfully completed rather than failing with a warning.
3. **Incident Detection Engine Resilience:**
   - `EventDetectionEngine.process_video_events` executes safely with non-existent camera/video IDs without throwing uncaught exceptions.

---

## 11. Timeout & Long CCTV Footage (Step 10)

1. **Multi-Window Temporal Slicing:**
   - Tested X3D temporal slicing on 100-frame video (4.0s @ 25 FPS).
   - Window planner generated 3 sliding windows: `[0.0s, 2.0s]`, `[1.0s, 3.0s]`, `[2.0s, 4.0s]`.
   - Window indices strictly respected video length and produced valid temporal boundaries.
2. **Preprocessing Tensor Bounds:**
   - For any window size, `preprocess_clip` normalizes and resamples frames to uniform tensor shape `(1, 3, 16, 224, 224)` without exceeding array bounds.

---

## 12. Frontend Error Handling Contracts (Step 11)

Inspected the frontend React SPA error contracts:
- **HTTP 401 Unauthorized:** Axios interceptor automatically logs out the user and redirects to `/login`.
- **HTTP 403 Forbidden:** Returns standard JSON `{"detail": "..."}`; UI displays error card.
- **HTTP 404 Not Found:** Returns standard JSON `{"detail": "..."}`.
- **HTTP 422 Unprocessable Entity:** Returns field validation breakdown.
- **HTTP 413 Payload Too Large:** UI displays `"Video file exceeds the 100MB limit."`

---

## 13. Resource Cleanup & Leaks (Step 12)

1. **Rejected Upload Disk Cleanup:**
   - If an upload is rejected due to size (>100MB), zero bytes, or stream corruption, the server immediately unlinks and deletes the file from disk (`os.remove(saved_path)`).
   - Confirmed `storage/` directory file count before and after rejected upload is identical.
2. **OpenCV VideoCapture Handles:**
   - `check_video_integrity()` calls `cap.release()` in all execution branches. File handles are released immediately, preventing Windows file locking (`PermissionError: [WinError 32]`).
3. **Qdrant Reprocessing Cleanup:**
   - `vector_store.delete_vectors_by_video_id()` executes on re-processing to prevent accumulation of orphan vectors.

---

## 14. Failure Classification & Findings (Step 13)

| ID | Severity | Component | Failure Scenario | Impact | Recommended Remediation |
| :--- | :---: | :--- | :--- | :--- | :--- |
| **FAIL-01** | **HIGH** | Database / SQLite Dialect | Pure-digit UUIDs coerced to `float` by SQLite dynamic affinity | Crashes SQLAlchemy deserialization with `'float' object has no attribute 'replace'` | Add a custom SQLite-compatible UUID TypeDecorator in `config.py` similar to `SqliteCompatibleArray`. |
| **FAIL-02** | **HIGH** | Violence Pipeline (`POST /violence/analyze`) | Unhandled inference or runtime exception during X3D-M execution | Video status remains stuck in `status="processing"` indefinitely in DB | Wrap `detect_violence()` in a `try...except` block that updates `target_video.status = "failed"` and commits. |
| **FAIL-03** | **MEDIUM** | General Pipeline (`orchestrator.py`) | Video with 0 frames or invalid FPS produces 0 detections | Pipeline finishes with `status="completed"` and 100% progress (silent false success) | In Stage 1, raise `ValueError("Video contains no decodable frames")` if `frame_count == 0` or `fps <= 0`. |
| **FAIL-04** | **MEDIUM** | Reports API (`POST /reports/generate`) | Repeated report generation on the same incident | Creates duplicate redundant Report records | Implement idempotency check: return existing report if one was already generated for `incident_id`. |
| **FAIL-05** | **LOW** | Celery Worker (`video_tasks.py`) | Eager execution vs daemon worker disconnect in `.env` | Tasks run in synchronous caller thread when `CELERY_ALWAYS_EAGER=true` | Document eager fallback mode for single-node deployments. |

---

## 15. Resilience Test Suite Execution (Step 14)

```
Test File: backend/tests/resilience/test_resilience_validation.py
Command: pytest backend/tests/resilience/test_resilience_validation.py -v

============================== test session starts ==============================
collected 43 items

test_env_baseline_components                              PASSED [  2%]
test_invalid_video_zero_byte_violence_upload              PASSED [  4%]
test_invalid_video_zero_byte_general_upload               PASSED [  6%]
test_invalid_video_corrupted_mp4_violence_upload          PASSED [  9%]
test_invalid_video_truncated_mp4_violence_upload          PASSED [ 11%]
test_invalid_video_fake_container_text_file               PASSED [ 13%]
test_invalid_video_unsupported_extension                  PASSED [ 16%]
test_invalid_video_oversized_file                         PASSED [ 18%]
test_invalid_video_extremely_short_integrity              PASSED [ 20%]
test_invalid_video_fewer_than_16_frames_x3d               PASSED [ 23%]
test_invalid_video_unusual_fps                            PASSED [ 25%]
test_invalid_video_zero_fps_videoreader                   PASSED [ 27%]
test_missing_video_id_violence_analyze                    PASSED [ 30%]
test_missing_video_status                                 PASSED [ 32%]
test_missing_camera_resource                              PASSED [ 34%]
test_missing_incident_resource                            PASSED [ 37%]
test_missing_student_resource                             PASSED [ 39%]
test_missing_storage_evidence_file                        PASSED [ 41%]
test_missing_report_download                              PASSED [ 44%]
test_missing_model_checkpoint_x3d                         PASSED [ 46%]
test_x3d_inference_exception_handling                     PASSED [ 48%]
test_face_engine_missing_crop                             PASSED [ 51%]
test_yolo_detector_exception_handling                     PASSED [ 53%]
test_clip_embedder_failure                                PASSED [ 55%]
test_db_unique_constraint_violation                       PASSED [ 58%]
test_db_connection_error_handling                         PASSED [ 60%]
test_celery_task_permanent_error_handling                 PASSED [ 62%]
test_celery_enqueue_failure_handling                      PASSED [ 65%]
test_qdrant_connection_error_upsert                       PASSED [ 67%]
test_qdrant_search_error_api                              PASSED [ 69%]
test_duplicate_video_upload_creates_isolated_ids          PASSED [ 72%]
test_repeated_report_generation                           PASSED [ 74%]
test_pipeline_stage1_validation_failure                   PASSED [ 76%]
test_pipeline_incident_engine_resilience                  PASSED [ 79%]
test_long_video_processing_simulation                     PASSED [ 81%]
test_sliding_window_bounds                                PASSED [ 83%]
test_frontend_error_mapping_401                           PASSED [ 86%]
test_frontend_error_mapping_403                           PASSED [ 88%]
test_frontend_error_mapping_404                           PASSED [ 90%]
test_frontend_error_mapping_422                           PASSED [ 93%]
test_cleanup_temp_file_on_upload_rejection                PASSED [ 95%]
test_videocapture_release_on_error                        PASSED [ 97%]
test_vector_store_clean_reprocessing                      PASSED [100%]

============================== 43 passed in 19.89s ==============================
```

---

## 16. Final Resilience Verdict

**`RESILIENCE VERIFIED WITH LIMITATIONS`**

The core ingestion, file validation, storage cleanup, error propagation, and vector fallback mechanisms function robustly. However, real engineering limitations were empirically identified:
1. SQLite column affinity can corrupt pure-numeric UUID strings into floats.
2. Unhandled X3D-M inference crashes in `/violence/analyze` leave video assets in a perpetual `"processing"` state.
3. Empty video files in the general pipeline pass through to `"completed"` without warning.
4. Report generation lacks idempotency for duplicate requests.

Per the Phase 5 instructions, **no code was altered to hide or fix these findings**. Phase 5 is complete and locked.
