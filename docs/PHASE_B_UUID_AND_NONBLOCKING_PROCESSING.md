# PHASE B — UUID FOREIGN-KEY FIX & NON-BLOCKING VIDEO PROCESSING REPORT

**Project:** AI-Powered Smart CCTV Investigation System  
**Workspace:** `C:\Users\Asus\OneDrive\Desktop\AI-Powered Smart CCTV Investigation System`  
**Phase:** Phase B — UUID Foreign-Key Fix & Non-Blocking Video Processing  
**Status:** COMPLETE & EMPIRICALLY VERIFIED

---

## 1. Root Cause Confirmed

### Defect 1: UUID Representation Mismatch causing Foreign-Key Integrity Failures
- **Root Cause:** Historical student records in the local SQLite database (`backend/storage/cctv.db`) had primary keys stored as 32-character hexadecimal strings (e.g. `b60b7e846fcc4dac8255007fc24cfdb6`), without hyphens.
- During Stage 6 Face Recognition (`app/services/student_identifier.py`), matched student IDs returned from Qdrant/face matching were parsed via `uuid.UUID(student_id)`.
- When constructing `StudentRecognitionEvent(student_id=...)` in `app/pipeline/orchestrator.py`, SQLAlchemy bound the foreign key parameter as a canonical 36-character hyphenated UUID string (e.g. `b60b7e84-6fcc-4dac-8255-007fc24cfdb6`).
- Because runtime SQLite foreign-key enforcement is enabled (`PRAGMA foreign_keys = ON;`), SQLite executes byte-for-byte string comparisons between child foreign keys and parent primary keys. The string format mismatch caused SQLite to reject the insert: `sqlite3.IntegrityError: FOREIGN KEY constraint failed`.

### Defect 2: Blocking Video Processing During Upload in Local Eager-Celery Mode
- **Root Cause:** In the local development environment without Redis (`CELERY_ALWAYS_EAGER = True`), Celery executes tasks synchronously on the calling thread.
- The upload route (`POST /api/v1/videos/upload`) invoked `process_video.delay(str(video.id))`.
- Under default Celery eager semantics, `.delay()` executed the entire 8-stage AI inference pipeline (YOLOv8 + ByteTrack + X3D-M + ArcFace) synchronously within the FastAPI request-response lifecycle.
- This blocked the HTTP response for 50–60+ seconds, preventing frontend status polling, starving connection pools, and degrading browser responsiveness.

---

## 2. Files Modified

| File | Type | Description |
|---|---|---|
| [`backend/app/db/base_class.py`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/db/base_class.py) | Core DB Model | Updated [`SqliteCompatibleUUID`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/db/base_class.py#L35-L68) to transparently normalize `uuid.UUID` objects, 32-char hex strings, and 36-char hyphenated strings into canonical 36-character strings on bind and `uuid.UUID` objects on result retrieval. |
| [`backend/app/core/config.py`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/core/config.py) | Configuration | Synchronized [`SqliteCompatibleUUID`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/core/config.py#L35-L68) definition with base class. |
| [`backend/app/main.py`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/main.py) | Application Startup | Added idempotent, atomic startup normalization migrating legacy 32-character hex student IDs and all 8 referencing foreign-key tables into canonical 36-character UUID strings. |
| [`backend/app/tasks/video_tasks.py`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/tasks/video_tasks.py) | Task Pipeline | Introduced [`BackgroundEagerTask`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/tasks/video_tasks.py#L20-L38) with dedicated single-worker [`_background_executor`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/tasks/video_tasks.py#L17). Asynchronous `.delay()` dispatches to background worker while preserving synchronous direct `.apply()` execution for test harnesses. |
| [`backend/tests/database/test_database_integrity.py`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/tests/database/test_database_integrity.py) | Test Suite | Updated legacy test expectation in `test_3_foreign_key_integrity_and_divergence` to recognize active runtime foreign-key enforcement. |
| [`backend/tests/test_phase_b_uuid_and_nonblocking.py`](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/tests/test_phase_b_uuid_and_nonblocking.py) | New Test Suite | Comprehensive unit and integration regression suite covering UUID conversions, legacy/canonical FK insertion under `PRAGMA foreign_keys=ON;`, invalid FK rejection, non-blocking video dispatch latency, and exception handling. |

---

## 3. UUID Compatibility Strategy

1. **Dual Representation Acceptance**:
   - `SqliteCompatibleUUID.process_bind_param` accepts `uuid.UUID` objects, 32-character hexadecimal strings, and 36-character hyphenated strings.
   - All representations are canonicalized into standard 36-character hyphenated UUID strings (`str(uuid.UUID(str(value)))`) prior to SQLite persistence.
2. **Result Value Consistency**:
   - `SqliteCompatibleUUID.process_result_value` converts stored strings back into native Python `uuid.UUID` instances, guaranteeing round-trip type stability across ORM models.
3. **Foreign Key Alignment**:
   - Because all bindings are normalized to 36-character hyphenated strings, foreign keys in child tables (`student_recognition_events`, `incident_persons`, `reports`, `tracks`) byte-for-byte match the parent `students.id`.

---

## 4. Data Normalization & Database Protection

### Safety Pre-requisites Executed
- Safe SQLite backup created via SQLite online backup API before modifications:
  - `backend/storage/cctv.db.backup_phase_b_safety` (Size: 11,915,264 bytes)
  - `backend/storage/cctv.db.pristine_backup` (Size: 11,915,264 bytes)
- Schema and relationship audit executed prior to normalization:
  - 36 of 41 students had legacy 32-character hex IDs.
  - Zero UUID collisions found upon 36-character hyphen normalization.
  - Normalization mapped across all 8 referencing tables:
    - `students.id`
    - `student_photos.student_id`
    - `student_face_sessions.student_id`
    - `student_face_embeddings.student_id`
    - `student_recognition_events.student_id`
    - `incident_persons.student_id`
    - `reports.student_id`
    - `tracks.identified_student_id`
    - `events.student_id`
- Reversible, idempotent transaction in `app/main.py`:
  - Normalization checks `SELECT id FROM students WHERE length(id) = 32`.
  - If found, executes within an atomic transaction.
  - Verification with `PRAGMA foreign_key_check` confirmed 0 new foreign key violations were introduced.

---

## 5. Background Execution Strategy & Durability Limitations

### Strategy
- Created `BackgroundEagerTask(Task)` as the base class for Celery tasks in `app/tasks/video_tasks.py`.
- When `settings.CELERY_ALWAYS_EAGER` is active, task invocations through `.apply_async()` / `.delay()` offload work to a dedicated, bounded `ThreadPoolExecutor(max_workers=1, thread_name_prefix="video_proc_")`.
- The HTTP upload handler receives immediate control back from `.delay()`, returns HTTP 201 with `status: "queued"`, and allows the frontend to begin status polling.
- Direct invocations via `.apply(...)` run synchronously on the caller's thread, preserving compatibility with unit tests.
- Task execution lifecycle creates and disposes of its own `AsyncSession` (`async with SessionLocal() as db:`), avoiding shared database transactions with HTTP requests.
- Application shutdown registered via `atexit.register(lambda: _background_executor.shutdown(wait=False))`.

### Durability Limitations
- In local eager mode without Redis or persistent message brokers, tasks in the thread pool are memory-bound.
- If the backend process crashes or restarts while a video task is queued or executing, the task will not survive the crash.
- Durable queuing requires a persistent broker (Redis or RabbitMQ) in production mode (`CELERY_ALWAYS_EAGER = False`).

---

## 6. Tests Executed & Exact Results

All test suites were executed using Python 3.11 in the project Conda environment:

| Test Suite | Passed | Failed | Skipped | Status |
|---|---|---|---|---|
| `tests/test_phase_b_uuid_and_nonblocking.py` | 6 | 0 | 0 | **PASSED** |
| `tests/database/test_database_integrity.py` | 13 | 0 | 1* | **PASSED** |
| `tests/database/test_database_remediation.py` | 12 | 0 | 1* | **PASSED** |
| `tests/resilience/test_resilience_validation.py` | 43 | 0 | 0 | **PASSED** |
| `tests/resilience/test_resilience_remediation.py` | 15 | 0 | 0 | **PASSED** |
| `tests/api/test_api_contract_validation.py` | 26 | 0 | 0 | **PASSED** |
| `tests/security/test_security_validation.py` | 34 | 0 | 0 | **PASSED** |
| `tests/security/test_security_remediation.py` | 48 | 0 | 0 | **PASSED** |
| **TOTAL** | **197** | **0** | **2** | **100% SUCCESS** |

*\*Note: 2 tests skipped correspond to live PostgreSQL server parity checks because the local environment runs on SQLite fallback mode.*

---

## 7. Upload & API Latency Measurements

Empirical measurements gathered via `scratch/verify_phase_b_performance.py` against the running application:

- **Upload Request Response Time (`POST /api/v1/videos/upload`)**: **69.18 ms** (0.0692 s)  
  *(Down from 50–60+ seconds blocking duration)*
- **Time Until Processing Began**: **76.19 ms**
- **Average Concurrent API Latency During Video Processing (`GET /api/v1/cameras`)**: **12.18 ms**
- **Min / Max Concurrent API Latency**: **8.01 ms / 16.01 ms**
- **Video Status Progression**: `queued` -> `processing (Validation 5%)` -> `processing (Stage 1-8 20%)` -> `completed (100%)`
- **Total Processing Duration**: **1.05 s** (for sample test video)
- **Final Video Status**: `completed`
- **Final Error Message**: `None`

---

## 8. Database Integrity Results

- Verification query on previously failing student IDs from video `c68b9336-8a6d-46c7-b085-70d365471bcd`:
  - `0dafc27f-09a1-4ea7-8764-743fe7e72da1` (Ashish P) -> **CANONICAL 36-CHAR**
  - `b60b7e84-6fcc-4dac-8255-007fc24cfdb6` (Anukutty) -> **CANONICAL 36-CHAR**
- Direct insertion test with previous failure parameters under `PRAGMA foreign_keys = ON;`: **SUCCESS (0 errors)**.
- Insertion of invalid student parent references under `PRAGMA foreign_keys = ON;`: **Correctly rejected with `sqlite3.IntegrityError`**.

---

## 9. Security Regression Results

- Authentication, JWT validation, token lifetime hardening, and RBAC passed (34/34 validation, 48/48 remediation).
- IDOR protections for video deletion and report access verified intact.
- Storage directory traversal protections and database file direct access blocks verified.
- WebSocket token authorization verified intact.

---

## 10. X3D-M Checkpoint Hash Comparison

- Checkpoint Path: `storage/models/x3d/final_x3d_realtime.pt`
- Baseline SHA-256: `e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349`
- Current SHA-256:  `e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349`
- Status: **IDENTICAL (100% UNTOUCHED)**

---

## 11. Unresolved Issues

- **None.** Both defects identified in the Phase A diagnosis have been resolved and regression tested.
- Note on Qdrant vector store in local multi-process execution: Qdrant client uses an exclusive file lock on `storage/qdrant_db`. When Uvicorn is active, tests set `QDRANT_IN_MEMORY=true` to maintain isolated memory collections, as established by the project configuration.
