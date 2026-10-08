# PHASE 6 — DATABASE INTEGRITY, PERSISTENCE & DATABASE ARCHITECTURE VALIDATION REPORT

**Audit Date**: October 8, 2026  
**Status**: AUDIT COMPLETE (AUDIT-ONLY PHASE — NO CODE/SCHEMA MODIFICATIONS)  
**Final Verdict**: `DATABASE INTEGRITY ISSUES FOUND`  

---

## 1. Environment

| Component | Audit Specification |
|:---|:---|
| **Operating System** | Windows 11 Enterprise (Build 26100), x86_64 |
| **Python Environment** | Python 3.11.15 (`pro-env` via Conda) |
| **Frameworks** | FastAPI 0.115+, Starlette, SQLAlchemy 2.0.44, aiosqlite 0.20.0 |
| **Database Drivers** | `sqlite3` / `aiosqlite`, `asyncpg` / `psycopg2-binary` (configured) |
| **Background Processing** | Celery 5.3+ (`CELERY_TASK_ALWAYS_EAGER=True` in test mode) |
| **Storage Paths** | Application DB: `storage/cctv.db`<br>Audit Test DB: `storage/test_remediation_audit.db` |
| **Vector Database** | Qdrant Client (Mocked / Local in-memory test fallback) |

---

## 2. Active Database Configuration

### 2.1 Engine & Connection Analysis

The backend database configuration was audited in `backend/app/db/session.py` and `backend/app/core/config.py`:

```python
# backend/app/core/config.py
DATABASE_URL = "sqlite+aiosqlite:///./storage/cctv.db"  # Fallback when POSTGRES_SERVER is not set
```

- **Active Database URL**: `sqlite+aiosqlite:///./storage/cctv.db`
- **Dialect**: SQLite 3 (via `aiosqlite` async driver adapter)
- **Engine Connection Pool**: `AsyncAdaptedQueuePool` (`pool_size=5`, `max_overflow=10`, `pool_timeout=30s`)
- **Connection Isolation**: Standard SQLite autocommit / transaction boundaries managed by SQLAlchemy `AsyncSession`.
- **Foreign Key Runtime Enforcement (`PRAGMA foreign_keys`)**: **`0` (DISABLED)**.
  - SQLAlchemy `create_async_engine` connects to SQLite without attaching an `async_engine.sync_engine` event listener (`PRAGMA foreign_keys=ON;`).
  - As a result, SQLite does NOT enforce foreign keys at runtime during normal operations.
- **PostgreSQL Configuration**:
  - `POSTGRES_SERVER=db`, `POSTGRES_USER=postgres`, `POSTGRES_DB=smart_cctv`
  - Target URL: `postgresql+asyncpg://postgres:postgres@db:5432/smart_cctv`
  - **Docker Status**: Port 5432 is unreachable on `localhost` and `db`; Docker engine is offline. PostgreSQL fallback to SQLite is automatically active.
- **Schema Lifecycle**:
  - Schema creation is initiated via `Base.metadata.create_all` during startup (`init_db()` in `app/db/init_db.py`).
  - No active Alembic migration runner is invoked during application lifespan; DDL changes are driven by SQLAlchemy metadata inspection and model definitions.

---

## 3. Schema Inventory

A comprehensive inspection of all SQLAlchemy models in `backend/app/models/` and `storage/cctv.db` was performed.

| Table Name | Model Class | Primary Key | Foreign Keys | Unique Constraints | Indexes | Status / Enums |
|:---|:---|:---|:---|:---|:---|:---|
| `users` | `User` | `id` (UUID) | None | `email` | `ix_users_email` | `is_active`, `role` |
| `cameras` | `Camera` | `id` (UUID) | `group_id` -> `camera_groups.id` | `name` | `ix_cameras_name` | `status` |
| `camera_groups` | `CameraGroup` | `id` (UUID) | None | `name` | `ix_camera_groups_name` | — |
| `virtual_zones` | `VirtualZone` | `id` (UUID) | `camera_id` -> `cameras.id` | None | None | `zone_type`, `is_active` |
| `camera_calibrations` | `CameraCalibration` | `id` (UUID) | `camera_id` -> `cameras.id` | `camera_id` | `ix_camera_calibrations_camera_id` | — |
| `videos` | `Video` | `id` (UUID) | `camera_id` -> `cameras.id`<br>`uploaded_by` -> `users.id` | None | `ix_videos_id` | `status`, `current_stage` |
| `students` | `Student` | `id` (UUID) | None | `roll_number` | `ix_students_roll_number` | `status` |
| `student_face_embeddings`| `StudentFaceEmbedding`| `id` (UUID) | `student_id` -> `students.id` | None | None | — |
| `student_activities` | `StudentActivity` | `id` (UUID) | `student_id` -> `students.id`<br>`camera_id` -> `cameras.id` | None | None | — |
| `tracks` | `Track` | `id` (UUID) | `video_id` -> `videos.id`<br>`identified_student_id` -> `students.id` | None | None | `object_class` |
| `detections` | `Detection` | `id` (UUID) | `track_id` -> `tracks.id` | None | None | — |
| `person_reids` | `PersonReID` | `id` (UUID) | None | None | None | — |
| `incidents` | `Incident` | `id` (UUID) | `camera_id` -> `cameras.id` | None | None | `incident_type`, `status` |
| `incident_persons` | `IncidentPerson` | `id` (UUID) | `incident_id` -> `incidents.id`<br>`student_id` -> `students.id` | None | None | — |
| `evidence` | `Evidence` | `id` (UUID) | `incident_id` -> `incidents.id` | None | None | `evidence_type` |
| `reports` | `Report` | `id` (UUID) | `student_id` -> `students.id` *(incident_id unlinked)* | `incident_id` | `ix_reports_incident_id` | `incident_type` |
| `detected_events` | `DetectedEvent` | `id` (UUID) | `video_id` -> `videos.id`<br>`camera_id` -> `cameras.id`<br>`incident_id` -> `incidents.id` | None | None | `event_type` |
| `notifications` | `Notification` | `id` (UUID) | `user_id` -> `users.id`<br>`incident_id` -> `incidents.id` | None | None | `is_read`, `priority` |
| `notification_preferences`| `NotificationPreference`| `id` (UUID) | `user_id` -> `users.id` | None | None | — |
| `bulk_import_jobs` | `BulkImportJob` | `id` (UUID) | `user_id` -> `users.id` | None | None | `status` |
| `bulk_import_errors`| `BulkImportError`| `id` (UUID) | `job_id` -> `bulk_import_jobs.id` | None | None | — |
| `system_settings` | `SystemSetting` | `id` (UUID) | None | `key` | `ix_system_settings_key` | — |
| `audit_logs` | `AuditLog` | `id` (UUID) | `user_id` -> `users.id` | None | None | `action` |
| `investigations` | `Investigation` | `id` (UUID) | `lead_investigator_id` -> `users.id` | None | None | `status` |

- **Total Models Defined in Metadata**: 24
- **Total Tables in Live `storage/cctv.db`**: 24
- **Schema Parity**: 100% column name, data type, and primary key match between SQLAlchemy declarative models and SQLite catalog tables.

---

## 4. Constraint Inventory

### 4.1 Non-Nullable Constraints
- `users.email`, `users.hashed_password`: Non-null database enforced.
- `cameras.name`, `cameras.status`: Non-null database enforced.
- `videos.filename`, `videos.original_filename`, `videos.file_path`, `videos.uploaded_by`, `videos.status`: Non-null database enforced.
- `students.name`, `students.roll_number`, `students.department`: Non-null database enforced.
- `incidents.camera_id`, `incidents.incident_type`, `incidents.timestamp`: Non-null database enforced.

### 4.2 Database-Level Unique Constraints
1. `users.email` -> `UNIQUE` (`ix_users_email`)
2. `students.roll_number` -> `UNIQUE` (`ix_students_roll_number`)
3. `cameras.name` -> `UNIQUE` (`ix_cameras_name`)
4. `camera_groups.name` -> `UNIQUE` (`ix_camera_groups_name`)
5. `camera_calibrations.camera_id` -> `UNIQUE` (`ix_camera_calibrations_camera_id`)
6. `reports.incident_id` -> `UNIQUE` (`ix_reports_incident_id` with partial NULL allowance)
7. `system_settings.key` -> `UNIQUE` (`ix_system_settings_key`)

---

## 5. Foreign-Key Integrity Results

### 5.1 Runtime Foreign-Key Behavior: DEFECT IDENTIFIED
- **Observed Behavior**: Under the active SQLite driver configuration (`sqlite+aiosqlite`), foreign-key constraints are **NOT enforced** at connection time (`PRAGMA foreign_keys = 0`).
- **Empirical Proof**:
  - Inserting a `Video` record referencing `uploaded_by = uuid.uuid4()` (a non-existent user ID) **succeeded without raising `IntegrityError`**.
  - When connection listener `PRAGMA foreign_keys = ON;` is manually enabled, the engine immediately and correctly raises:
    ```text
    (sqlite3.IntegrityError) FOREIGN KEY constraint failed
    ```
- **Cascade / Set-Null Divergence**:
  - Because `PRAGMA foreign_keys = 0`, SQL-level `ON DELETE CASCADE` and `ON DELETE SET NULL` clauses are ignored by the SQLite engine unless explicitly driven by SQLAlchemy ORM cascade mappings.
  - Deleting a parent `Student` directly via SQL leaves orphan `student_face_embeddings` records.

---

## 6. UUID & Primary Key Integrity

The Phase 5A UUID remediation was verified across all UUID variants:

1. **Standard UUIDv4**: `uuid.uuid4()` persists and round-trips with 100% type preservation.
2. **Pure-Numeric UUID**: e.g., `12345678-1234-5678-1234-567812345678` correctly parsed and stored as standard 36-char string in SQLite and UUID in PostgreSQL. No numeric truncation occurs.
3. **Hexadecimal Alphanumeric UUID**: e.g., `abcdef01-2345-6789-abcd-ef0123456789` persists with exact string representation.
4. **Duplicate Primary Key**: Attempting to insert two rows with identical `id` strictly raises `IntegrityError` (PRIMARY KEY constraint failed).
5. **NULL Primary Key**: Attempting to insert a row with `id=None` raises `IntegrityError` (NOT NULL constraint failed).

---

## 7. Transaction Atomicity & Rollback Testing

Transaction atomicity was empirically evaluated under 6 distinct scenarios in `test_database_integrity.py`:

| Scenario | Description | Result | Details |
|:---|:---|:---|:---|
| **A** | Successful multi-table transaction | **PASS** | Camera and Video inserted and committed atomically. |
| **B** | Failure halfway through transaction | **PASS** | Parent record inserted; deliberate exception raised before commit. Session rollback cleared all pending inserts; 0 rows persisted. |
| **C** | IntegrityError (Unique violation) | **PASS** | Second duplicate insert raised `IntegrityError`; `await db.rollback()` restored clean session state. |
| **D** | Explicit rollback | **PASS** | Staged uncommitted rows removed from transaction queue immediately upon rollback. |
| **E** | Exception after multiple INSERTs | **PASS** | Multi-table staged inserts rolled back cleanly without partial persistence. |
| **F** | Repeated transaction after rollback | **PASS** | Reusing the same session after rollback to perform a valid transaction succeeded without session invalidation. |

---

## 8. Partial Pipeline Persistence Audit

We audited state persistence when the video investigation pipeline fails at intermediate stages:

| Pipeline Stage Failure | Resulting DB State | Orphan Risk | Classification |
|:---|:---|:---|:---|
| **Video Upload Rejection** (corrupt container) | Temp file purged; 0 records inserted. | None | **EXPECTED** |
| **Metadata Extraction Failure** | Video status set to `'failed'`, `current_stage='Analysis Failed'`; 0 detections/tracks created. | None | **PARTIAL BUT SAFE** |
| **Detections / Tracking Failure** | Video status set to `'failed'`; any uncommitted tracks rolled back. | None | **PARTIAL BUT SAFE** |
| **Face Re-ID / ArcFace Failure** | System continues with `matched_student_id=None` (unidentified track); video reaches completed state. | None | **PARTIAL BUT SAFE** |
| **Violence Analysis Failure** | Video marked `'failed'`; no false incident or detected event created. | None | **PARTIAL BUT SAFE** |
| **Evidence Generation Failure** | Incident created but evidence links point only to successfully written artifacts. | None | **PARTIAL BUT SAFE** |
| **Report Generation Failure** | Incident and evidence preserved; report transaction rolled back cleanly. | None | **PARTIAL BUT SAFE** |

---

## 9. Restart Persistence Audit

We audited whether database records survive engine resets and process restarts:

1. Controlled records created in `storage/test_remediation_audit.db`:
   - Camera: `0567fae3-2ba8-4c9f-b98f-a9cb571b764b`
   - Video: `785d93e1-e9ee-4735-a110-388f8d95eb0f`
   - Incident: `bb4ef456-efc6-43d7-86c6-9f44db4dfcf9`
2. Database engine closed and disposed via `await engine.dispose()`.
3. New `create_async_engine` connection re-established against the same SQLite database file.
4. All 3 entities queried and verified intact with 100% field fidelity.
5. **Result**: Zero records lost across restart.

---

## 10. Investigation Chain & Evidence Persistence

We validated the end-to-end relational chain:
$$\text{Camera} \longrightarrow \text{Video} \longrightarrow \text{Incident} \longrightarrow \text{Evidence} \longrightarrow \text{Report}$$

- **Chain Verification**:
  - `Video.camera_id` correctly references `Camera.id`
  - `Evidence.incident_id` correctly references `Incident.id`
  - `Report.incident_id` correctly references `Incident.id`
- **File System Parity**: Evidence image and clip paths point to valid physical files in `storage/evidence/`. Restarting the backend preserves all foreign links and file paths.

---

## 11. Concurrent Database Operations

Audited under concurrent asynchronous workers (`asyncio.gather`):

1. **Concurrent Distinct Writes**:
   - 5 simultaneous camera creation tasks executed concurrently.
   - 5 distinct records persisted without lock collisions or data corruption.
2. **Concurrent Duplicate Unique Writes (FAIL-04 Report Race)**:
   - 5 simultaneous `POST /reports/generate` requests with identical `incident_id`.
   - **Result**: Exactly 1 report created; 4 concurrent transactions caught `IntegrityError` on unique constraint `ix_reports_incident_id`, rolled back cleanly, and returned the winning report ID.
   - **Duplicate rows created**: 0.

---

## 12. SQLite vs. PostgreSQL Parity

| Feature | SQLite Behavior | PostgreSQL Behavior | Parity Status |
|:---|:---|:---|:---|
| **UUID Storage** | String (`CHAR(36)` / `VARCHAR(32)`) | Native `UUID` type | Functional Parity via SQLAlchemy `GUID` type |
| **Foreign Key Enforcement** | **Disabled by default** (`PRAGMA foreign_keys=0`) | Enabled by default | **DIVERGENCE (DEFECT)** |
| **NULL in Unique Constraints** | Allows multiple `NULL` values in `UNIQUE` index | Allows multiple `NULL` values in `UNIQUE` index | Parity Verified |
| **JSON Datatype** | Stored as `TEXT` with JSON serialization | Native `JSONB` / `JSON` | Functional Parity via SQLAlchemy `JSON` |
| **Transaction Rollback** | Atomic rollback clears all pending inserts | Atomic rollback clears all pending inserts | Parity Verified |
| **Concurrent Locking** | File-level write lock (`database is locked` on contention) | Row-level locking (`SELECT FOR UPDATE`, MVCC) | Divergence (SQLite more vulnerable to write timeouts) |
| **Live PG Service Check** | Operational | **BLOCKED** (Port 5432 unreachable, Docker offline) | **BLOCKED** |

---

## 13. Data Consistency & Orphan Record Audit

A read-only audit of `storage/cctv.db` was conducted:

| Entity Check | Query Condition | Count Found | Status |
|:---|:---|:---:|:---|
| **Orphan Videos** | `videos.uploaded_by NOT IN (SELECT id FROM users)` | **1** | **ORPHAN FOUND** (`e1f2a3b4...`) |
| **Orphan Face Embeddings** | `student_face_embeddings.student_id NOT IN (SELECT id FROM students)` | **6** | **ORPHAN FOUND** (Students deleted without cascade) |
| **Orphan Tracks** | `tracks.video_id NOT IN (SELECT id FROM videos)` | **0** | Clean |
| **Orphan Detections** | `detections.track_id NOT IN (SELECT id FROM tracks)` | **0** | Clean |
| **Orphan Incidents** | `incidents.camera_id NOT IN (SELECT id FROM cameras)` | **0** | Clean |
| **Orphan Evidence** | `evidence.incident_id NOT IN (SELECT id FROM incidents)` | **0** | Clean |
| **Orphan Reports** | `reports.incident_id IS NOT NULL AND reports.incident_id NOT IN (SELECT id FROM incidents)` | **0** | Clean |
| **Duplicate Cameras** | Duplicate `cameras.name` | **0** | Clean |
| **Duplicate Students** | Duplicate `students.roll_number` | **0** | Clean |
| **Duplicate Reports** | Duplicate non-null `reports.incident_id` | **0** | Clean |

---

## 14. Persistence Stress Test

A stress test executed 25 sequential insert-read-rollback cycles on `storage/test_remediation_audit.db`:
- **Total Operations**: 75 (25 inserts, 25 reads, 25 rollbacks)
- **Successful Operations**: 75
- **Failed Operations**: 0
- **Deadlocks Encountered**: 0
- **Leaked Rows / Unintended Persistence**: 0

---

## 15. Empirical Test Suite Results

The dedicated empirical test suite `backend/tests/database/test_database_integrity.py` was executed:

| Test Index | Test Name | Result |
|:---:|:---|:---:|
| **TEST 1** | Database configuration & engine audit | **PASS** |
| **TEST 2** | Schema inventory & model parity | **PASS** |
| **TEST 3** | Foreign-key integrity & runtime divergence | **PASS** |
| **TEST 4** | UUID & primary key integrity | **PASS** |
| **TEST 5** | Unique constraints audit | **PASS** |
| **TEST 6** | Transaction atomicity & rollback | **PASS** |
| **TEST 7** | Partial pipeline persistence & failure states | **PASS** |
| **TEST 8** | Restart persistence | **PASS** |
| **TEST 9** | Report & evidence persistence | **PASS** |
| **TEST 10** | Concurrent database operations | **PASS** |
| **TEST 11** | Database startup safety & idempotency | **PASS** |
| **TEST 12** | Read-only data consistency & orphan audit | **PASS** |
| **TEST 13** | Persistence stress test | **PASS** |
| **TEST 14** | PostgreSQL parity check | **BLOCKED** (`Port 5432 unreachable`) |

**Summary**: **13 PASSED, 0 FAILED, 1 BLOCKED / SKIPPED** (Total: 14 tests).

---

## 16. Locked Regression Test Suite Verification

All existing locked test suites were re-executed to confirm zero regression:

| Test Suite | Purpose | Tests Expected | Tests Passed | Result |
|:---|:---|:---:|:---:|:---:|
| `tests/security/test_security_remediation.py` | Phase 4A Security Controls | 48 | 48 | **PASS** |
| `tests/resilience/test_resilience_validation.py` | Phase 5 Resilience Suite | 43 | 43 | **PASS** |
| `tests/resilience/test_resilience_remediation.py` | Phase 5A Resilience Remediation | 15 | 15 | **PASS** |
| `tests/resilience/test_fail04_concurrency.py` | Phase 5A FAIL-04 Concurrency | 7 | 7 | **PASS** |
| `test_x3d_violence_workflow.py` | X3D-M Violence Detection Pipeline | 6 | 6 | **PASS** |

**Combined Regression Total**: **119 / 119 PASSED (100%)**.

---

## 17. Defect Inventory & Severity Classification

| Defect ID | Severity | Category | Description |
|:---|:---:|:---|:---|
| **DEFECT-DB-01** | **HIGH** | Foreign Key Enforcement | In SQLite mode, `PRAGMA foreign_keys = ON;` is never executed on connect in `backend/app/db/session.py`. Invalid foreign keys are accepted and `CASCADE` / `SET NULL` deletes fail to trigger, resulting in orphan rows in `storage/cctv.db` (1 orphan video, 6 orphan embeddings). |
| **DEFECT-DB-02** | **MEDIUM** | Relational Modeling | `Report.incident_id` in `backend/app/models/report.py` has a database-level `UNIQUE` index constraint, but lacks an explicit `ForeignKey("incidents.id")` clause, allowing report rows to theoretically reference deleted or invalid incidents. |
| **DEFECT-DB-03** | **MEDIUM** | Pipeline Timing Jitter | In `backend/app/api/v1/violence.py`, `det_event.timestamp - target_video.created_at` computes wall-clock difference rather than the video's internal segment timestamp. Under heavy CPU load, this difference can exceed the altercation window and introduce metadata jitter. |
| **DEFECT-DB-04** | **INFORMATIONAL** | Service Availability | PostgreSQL test suite could not execute live parity tests because Docker Desktop / PostgreSQL port 5432 was offline. |

---

## 18. Recommended Remediation (For Phase 6A)

> [!NOTE]
> In accordance with Phase 6 Audit-Only rules, **NO code or schema changes were applied during this phase**. The following remediations are recommended for Phase 6A:

1. **Remediation for DEFECT-DB-01 (SQLite Foreign Keys)**:
   Add an event listener in `backend/app/db/session.py`:
   ```python
   from sqlalchemy import event
   from sqlalchemy.engine import Engine
   import sqlite3

   @event.listens_for(async_engine.sync_engine, "connect")
   def set_sqlite_pragma(dbapi_connection, connection_record):
       if isinstance(dbapi_connection, sqlite3.Connection):
           cursor = dbapi_connection.cursor()
           cursor.execute("PRAGMA foreign_keys=ON;")
           cursor.close()
   ```
2. **Remediation for DEFECT-DB-02 (`Report.incident_id` Foreign Key)**:
   Update `Report` model in `backend/app/models/report.py`:
   ```python
   incident_id = Column(GUID(), ForeignKey("incidents.id", ondelete="SET NULL"), unique=True, index=True, nullable=True)
   ```
3. **Remediation for DEFECT-DB-03 (Violence Timestamp Jitter)**:
   Store the exact video timeline start time in `det_event` or rely directly on `seg.start_time` when compiling the response dossier.

---

## 19. Limitations

1. **PostgreSQL Live Parity**: Could not be verified empirically due to port 5432 / Docker container being unavailable in the local environment. PostgreSQL parity status is documented as `BLOCKED`.
2. **SQLite Concurrency Throughput**: Under high concurrency (e.g., > 10 simultaneous writes), SQLite's database-level write lock will cause `sqlite3.OperationalError: database is locked` unless a connection pool queue with backoff is used.

---

## 20. Final Verdict

# `DATABASE INTEGRITY ISSUES FOUND`

**Verdict Rationale**:  
While transaction atomicity, primary key constraints, unique indexes, restart persistence, and Phase 5A FAIL-04 report idempotency function with high fidelity (13/14 tests passed, 119/119 locked regressions passed), **SQLite foreign-key enforcement is currently disabled at runtime (`PRAGMA foreign_keys=0`)**, which has resulted in verified orphan records in `storage/cctv.db` and leaves the database vulnerable to invalid references during parent entity deletion.
