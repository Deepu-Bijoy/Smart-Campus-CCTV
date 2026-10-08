# PHASE 6A — DATABASE INTEGRITY REMEDIATION & REGRESSION REPORT

**Remediation Date**: October 8, 2026  
**Status**: REMEDIATION & REGRESSION COMPLETE  
**Final Phase 6A Verdict**: `DATABASE INTEGRITY VERIFIED WITH LIMITATIONS`  
**Limitations Note**: PostgreSQL live parity verification blocked due to local Docker service unavailability (Port 5432 unreachable); all SQLite database integrity mechanisms, foreign keys, cascading deletions, SET NULL actions, unique constraints, report idempotency, and video-relative violence timestamps are 100% empirically verified.

---

## 1. Executive Summary & Defect Tracking

Phase 6 performed a comprehensive empirical audit of the database layer and identified four distinct defects. Phase 6A strictly remediated DEFECT-DB-01, DEFECT-DB-02, and DEFECT-DB-03 while assessing DEFECT-DB-04 under strict architectural and safety boundaries.

| Defect ID | Severity | Description | Remediation Status | Verification |
|:---|:---:|:---|:---:|:---:|
| **DEFECT-DB-01** | **HIGH** | SQLite foreign-key enforcement disabled at runtime (`PRAGMA foreign_keys = 0`). | **REMEDIATED** | `PRAGMA foreign_keys = 1` enforced on all connections via SQLAlchemy `engine.sync_engine` connect event listener. Invalid FKs rejected, ON DELETE CASCADE and SET NULL operational. |
| **DEFECT-DB-02** | **MEDIUM** | `Report.incident_id` lacked explicit foreign-key relationship to `incidents.id`. | **REMEDIATED** | Explicit `ForeignKey("incidents.id", ondelete="SET NULL")` added. UNIQUE constraint and multiple NULL allowance preserved; idempotency verified. |
| **DEFECT-DB-03** | **MEDIUM** | Violence dossier segment timestamps derived from wall-clock event time instead of video internal timeline. | **REMEDIATED** | Dossier compilation logic updated to extract video-relative segment bounds (`start_time`, `end_time`, `duration`) directly from X3D-M temporal altercation output. |
| **DEFECT-DB-04** | **INFORMATIONAL** | PostgreSQL live parity testing blocked due to local Docker service offline. | **BLOCKED (DOCUMENTED)** | Local Docker daemon offline / unresponsive; port 5432 unreachable. Database architecture preserved without artificial modification. |

---

## 2. DEFECT-DB-01 Remediation: SQLite Foreign Key Enforcement

### 2.1 Root Cause Analysis
In SQLAlchemy 2.0 with the `aiosqlite` async driver adapter, SQLite connections default to foreign key enforcement disabled (`PRAGMA foreign_keys = 0`). Because foreign key enforcement in SQLite is connection-scoped, issuing the pragma on a single initialization connection does not affect recycled or newly opened pool connections.

### 2.2 Implemented Fix
In [session.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/db/session.py#L27-L36), attached an event listener to the underlying synchronous engine (`engine.sync_engine`):

```python
# backend/app/db/session.py
if "sqlite" in db_uri:
    from sqlalchemy import event
    import sqlite3

    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()
```

### 2.3 Empirical Verification
1. **Runtime Pragma Setting**: New connections and recycled connections query `PRAGMA foreign_keys;` and report `1` (`test_db01_sqlite_pragma_foreign_keys_enabled`, `test_db01_pooled_connection_behavior`).
2. **Invalid Foreign Key Insertion**: Attempting to insert a `Video` referencing a non-existent `uploaded_by` user raises `sqlite3.IntegrityError: FOREIGN KEY constraint failed` (`test_db01_invalid_fk_rejected`).
3. **ON DELETE CASCADE**: Deleting a camera automatically deletes associated incidents (`test_db01_cascade_behavior`).
4. **ON DELETE SET NULL**: Deleting a student sets `student_id` to `NULL` on dependent records (`test_db01_set_null_behavior`).

---

## 3. DEFECT-DB-02 Remediation: Report Incident Foreign Key

### 3.1 Model Changes
In [report.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/report.py#L15-L17), added an explicit foreign key pointing to `incidents.id` with `ondelete="SET NULL"`, while maintaining the database-level `UNIQUE` index:

```python
# backend/app/models/report.py
incident_id: Mapped[Optional[uuid.UUID]] = mapped_column(
    UUID(as_uuid=True), 
    ForeignKey("incidents.id", ondelete="SET NULL"), 
    nullable=True, 
    unique=True, 
    index=True
)
```

### 3.2 Startup Migration & Idempotency
In [main.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/main.py#L173-L225), added safe, idempotent migration logic:
1. **Pre-Migration Audit**: Audited existing reports for invalid `incident_id` references before applying constraints:
   ```sql
   SELECT id, incident_id FROM reports 
   WHERE incident_id IS NOT NULL AND incident_id NOT IN (SELECT id FROM incidents)
   ```
   **Audit Result**: Exactly 0 invalid reports found in active database `storage/cctv.db`.
2. **Schema Evolution**: Safely checked `PRAGMA foreign_key_list(reports)`. If the foreign key is absent, evolved the table using standard SQLite table migration while preserving all data.
3. **Unique Index Preservation**: Enforced `CREATE UNIQUE INDEX IF NOT EXISTS ix_reports_incident_id ON reports(incident_id)`.
4. **Lifecycle Idempotency**: Verified multiple successive startup runs (3 consecutive cycles executed without error, index recreation, or table modification).

### 3.3 Empirical Verification
1. **Valid Incident Reference**: Report referencing active incident is committed cleanly (`test_db02_valid_report_to_incident`).
2. **Non-Existent Incident Reference**: Report referencing random UUID is rejected with `IntegrityError` (`test_db02_invalid_incident_rejected`).
3. **ON DELETE SET NULL**: Deleting the parent incident via `DELETE FROM incidents WHERE id = :id` sets `report.incident_id` to `NULL` while preserving the report entity (`test_db02_incident_deletion_sets_null`).
4. **Uniqueness**: Attempting to insert two reports with identical non-null `incident_id` raises `IntegrityError` (`test_db02_duplicate_incident_id_rejected`).
5. **Multiple NULL Values**: Multiple reports with `incident_id = None` are accepted simultaneously (`test_db02_multiple_null_incident_ids_allowed`).
6. **Report Idempotency**: Repeated report generation requests reuse the existing report (`test_repeated_report_generation`).

---

## 4. DEFECT-DB-03 Remediation: Violence Timestamp Integrity

### 4.1 Root Cause Analysis
In `_compile_violence_dossier` ([violence.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/violence.py)), segment timestamps were derived from `(det_event.timestamp - target_video.created_at).total_seconds()`. If background video processing or model analysis was delayed by hours or days after upload, the dossier displayed artificial multi-hour offsets instead of the video's actual 0-to-N internal temporal segment coordinates.

### 4.2 Implemented Fix
Updated `_compile_violence_dossier` in [violence.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/violence.py#L705-L745):
1. Segments extract exact video-relative start, end, and duration bounds directly from the X3D-M temporal analysis result (persisted in `Incident.explanation`: `"detected physical altercation from {start}s to {end}s"`).
2. Segment start and duration are mapped directly:
   ```python
   if seg_start_extracted is not None and seg_end_extracted is not None:
       start_t = seg_start_extracted
       end_t = seg_end_extracted
       duration = seg_dur_extracted or max(0.1, round(end_t - start_t, 1))
   ```
3. Dossier timeline displays exact segment bounds (e.g. `00:00:01 - 00:00:03`).
4. Wall-clock processing latency does not alter the persisted segment timestamp.

### 4.3 Empirical Verification
1. **Video-Relative Bounds**: Given a video altercation at 1.0s to 3.0s, the compiled dossier reports `start_time = 1.0`, `end_time = 3.0`, `duration = 2.0s` (`test_db03_video_relative_timestamp_correctness`).
2. **Delay Invariance**: Simulating a 48-hour wall-clock processing delay between `video.created_at` and `event.timestamp` leaves the dossier timestamp at exactly 1.0s, with zero latency distortion (`test_db03_wall_clock_processing_delay_does_not_alter_segment_timestamp`).

---

## 5. DEFECT-DB-04: PostgreSQL Parity Status

### 5.1 Environment State & Service Diagnostic
- **Host Environment**: Windows 11 Enterprise
- **Docker Desktop**: Binary located at `C:\Program Files\Docker\Docker\Docker Desktop.exe`.
- **Diagnostic Execution**:
  - Launched Docker Desktop background process.
  - Inspected Docker Engine named pipe `//./pipe/dockerDesktopLinuxEngine`.
  - Pipe returned error: `open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.`
  - WSL subsystem shows `docker-desktop` distro stopped. Host machine requires interactive user authorization / sign-in for Docker Desktop virtualization engine.
  - Network probe on `localhost:5432` and `db:5432` confirmed connection refused (TCP port closed).
- **Parity Status**: `BLOCKED — PostgreSQL test unavailable (Port 5432 unreachable, Docker offline)`.
- **Architectural Boundary**: Per instructions, SQLite was NOT replaced with PostgreSQL, and database architecture was not redesigned.

---

## 6. Orphan Records Audit

Phase 6 discovered orphan records in active database `storage/cctv.db`. In compliance with the strict non-destructive policy, these records were audited and preserved without automatic deletion:

### 6.1 Orphan Video Record
- **Record ID**: `'a6418a59d9d04f7284b67cda606d4741'`
- **Title**: `"X3D Test Video"`
- **Parent Reference**: `uploaded_by = 'e1f2a3b4c5d678901234567890abcdef'`
- **Created At**: `2026-09-09 09:27:14`
- **Classification**: **Test Artifact**. Created during historical Phase 3 X3D pipeline smoke tests when `mock_user` UUID was not persisted into `users`.
- **Recommendation**: Retain in historical audit database. For future maintenance, associate with an archived system user or delete in an explicit cleanup migration.

### 6.2 Orphan Student Face Embeddings
- **Record Count**: 6 rows in `student_face_embeddings`.
- **Referenced Parent IDs**:
  - `student_id = 'd13c2b564ee24417be164bc6581ad54d'` (3 rows)
  - `student_id = 'f426f144891245c5b7592ad744e6bdee'` (3 rows)
- **Classification**: **Stale Test Artifacts**. Generated when test students were removed without cascading deletions in older development revisions.
- **Recommendation**: Retain in historical audit database. For future maintenance, clean up via `DELETE FROM student_face_embeddings WHERE student_id NOT IN (SELECT id FROM students)`.

---

## 7. Test Results: Database Integrity Remediation Suite

**File**: [test_database_remediation.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/tests/database/test_database_remediation.py)  
**Execution Command**: `pytest tests/database/test_database_remediation.py -v`

```
tests/database/test_database_remediation.py::test_db01_sqlite_pragma_foreign_keys_enabled PASSED [  7%]
tests/database/test_database_remediation.py::test_db01_invalid_fk_rejected PASSED [ 15%]
tests/database/test_database_remediation.py::test_db01_cascade_behavior PASSED [ 23%]
tests/database/test_database_remediation.py::test_db01_set_null_behavior PASSED [ 30%]
tests/database/test_database_remediation.py::test_db01_pooled_connection_behavior PASSED [ 38%]
tests/database/test_database_remediation.py::test_db02_valid_report_to_incident PASSED [ 46%]
tests/database/test_database_remediation.py::test_db02_invalid_incident_rejected PASSED [ 53%]
tests/database/test_database_remediation.py::test_db02_incident_deletion_sets_null PASSED [ 61%]
tests/database/test_database_remediation.py::test_db02_duplicate_incident_id_rejected PASSED [ 69%]
tests/database/test_database_remediation.py::test_db02_multiple_null_incident_ids_allowed PASSED [ 76%]
tests/database/test_database_remediation.py::test_db03_video_relative_timestamp_correctness PASSED [ 84%]
tests/database/test_database_remediation.py::test_db03_wall_clock_processing_delay_does_not_alter_segment_timestamp PASSED [ 92%]
tests/database/test_database_remediation.py::test_db04_postgresql_parity_check SKIPPED (PostgreSQL offline) [100%]

======================= 12 passed, 1 skipped in 13.09s =======================
```

---

## 8. Regression Suite Verification Matrix

All historical and locked validation suites were executed following Phase 6A remediation. Zero tests were weakened or deleted.

| Suite | Focus Area | Expected | Passed | Failed | Status |
|:---|:---|:---:|:---:|:---:|:---:|
| **Phase 6A Remediation** | Database integrity, foreign keys, set null, video-relative timing | 12 | 12 | 0 | **PASS** |
| **Phase 4A Security** | Auth, RBAC, IDOR, input validation, rate limits, session security | 48 | 48 | 0 | **PASS** |
| **Phase 5 Resilience** | Degradation, missing media, corrupt files, OOM, timeout recovery | 43 | 43 | 0 | **PASS** |
| **Phase 5A Remediation** | UUID affinity, pipeline state transitions, Celery config | 15 | 15 | 0 | **PASS** |
| **FAIL-04 Concurrency** | Concurrent report generation, DB uniqueness, race resolution | 7 | 7 | 0 | **PASS** |
| **X3D-M Workflow** | Pretrained neural video action recognition pipeline | 6 | 6 | 0 | **PASS** |
| **TOTAL REGRESSION** | **All System Suites Combined** | **131** | **131** | **0** | **PASS (100%)** |

---

## 9. Critical X3D-M Verification

DEFECT-DB-03 modified timestamp extraction from the altercation window only. To verify that neural model inference was not altered:

1. **Checkpoint File**: `storage/models/x3d/final_x3d_realtime.pt`
   - File Size: `12,268,364 bytes`
   - SHA-256 Hash: `e833f69d110f167cad4a6c38d385564bdb2f6de63d246e45cb03ff9aa17f0349` (**IDENTICAL**)
2. **Classification Threshold**: `0.40` (**IDENTICAL**)
3. **Temporal Window Size**: `2.0s` window, `1.0s` stride, `16 frames` input (**IDENTICAL**)
4. **Input Normalization**: Mean `(0.45, 0.45, 0.45)`, Std `(0.225, 0.225, 0.225)` (**IDENTICAL**)
5. **Model Architecture**: Pretrained `X3D-M` backbone with `Dropout(0.3) -> Linear(2048, 2)` head (**IDENTICAL**)
6. **Workflow Test Execution**: `backend/test_x3d_violence_workflow.py` executed end-to-end:
   - Verification 1: FightDetector intact -> PASS
   - Verification 2: X3D-M initialization on CUDA -> PASS
   - Verification 3: Normal video inference (0.385s) -> PASS
   - Verification 4: Temporal sliding windowing -> PASS
   - Verification 5: API upload and analyze pipeline -> PASS
   - Verification 6: Violence detected altercation segment workflow -> PASS (Altercation Window: `00:00:01 - 00:00:03`)

---

## 10. Remaining Limitations & Operating Guidance

1. **PostgreSQL Parity**: Live parity testing against PostgreSQL remains blocked until Docker Desktop virtualization daemon is activated with interactive user credentials on the host OS.
2. **Legacy 32-Character Hex Foreign Keys**: Historical records in `storage/cctv.db` stored UUIDs in 32-character hex format (`UUID.hex`). Newly created records use standard 36-character hyphenated UUIDs (`UUID`). In SQLite, raw SQL joins between legacy 32-character records and newly inserted 36-character records require string normalization (`replace(id, '-', '')`).
3. **Historical Orphan Cleanup**: The 1 orphan video and 6 orphan face embeddings identified during the Phase 6 audit remain preserved in `storage/cctv.db` in compliance with data safety policies.

---

## 11. Final Verdict

# `DATABASE INTEGRITY VERIFIED WITH LIMITATIONS`

- **SQLite Foreign Key Enforcement**: VERIFIED (`PRAGMA foreign_keys = 1` active across all sessions and pools)
- **Report Incident Foreign Key**: VERIFIED (`ON DELETE SET NULL` active, uniqueness enforced, idempotency preserved)
- **Violence Timestamp Integrity**: VERIFIED (Video-relative temporal bounds strictly preserved)
- **PostgreSQL Parity**: DOCUMENTED LIMITATION (Port 5432 unreachable, Docker daemon offline)
- **Regression Suite**: 131/131 tests passed (100% success rate)
- **Status**: PHASE 6A COMPLETE AND LOCKED. STOPPING RULE ENFORCED.
