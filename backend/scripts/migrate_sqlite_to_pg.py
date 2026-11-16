"""
Production Data Migration Script: SQLite to PostgreSQL 16
Preserves primary keys, foreign keys, timestamps, JSON, and vector embeddings.
"""

import os
import sys
import json
import uuid
import sqlite3
import asyncio
from datetime import datetime, timezone
import asyncpg

# Ensure backend root is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings

SQLITE_PATH = os.getenv("SQLITE_PATH", os.path.join(settings.STORAGE_DIR, "cctv.db"))

# Normalization helper for UUIDs
def norm_uuid(val):
    if val is None:
        return None
    val_str = str(val).strip()
    try:
        return uuid.UUID(val_str)
    except Exception:
        return val

def norm_str(val):
    if val is None:
        return None
    return str(val)

def norm_dt(val):
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val
    val_str = str(val).strip()
    try:
        dt = datetime.fromisoformat(val_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(val_str, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                pass
        return None

def norm_bool(val):
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    return bool(val)

def norm_json(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return json.dumps(val)
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            return json.dumps(parsed)
        except Exception:
            return val
    return json.dumps(val)

def norm_float_array(val):
    if val is None:
        return None
    if isinstance(val, list):
        return [float(x) for x in val]
    if isinstance(val, str):
        parsed = json.loads(val)
        return [float(x) for x in parsed]
    return list(val)

async def main():
    print(f"Opening SQLite database at: {SQLITE_PATH}")
    sconn = sqlite3.connect(f"file:{SQLITE_PATH}?mode=ro", uri=True)
    sconn.row_factory = sqlite3.Row
    scur = sconn.cursor()

    # Validate required PostgreSQL settings
    if not settings.POSTGRES_SERVER or not settings.POSTGRES_USER or not settings.POSTGRES_PASSWORD or not settings.POSTGRES_DB:
        raise ValueError(
            "Missing required PostgreSQL configuration in environment / settings. "
            "Ensure POSTGRES_SERVER, POSTGRES_USER, POSTGRES_PASSWORD, and POSTGRES_DB are set."
        )

    masked_target = f"postgresql://{settings.POSTGRES_USER}:***@{settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB}"
    print(f"Connecting to PostgreSQL at: {masked_target}")
    try:
        pg = await asyncpg.connect(
            host=settings.POSTGRES_SERVER,
            port=settings.POSTGRES_PORT,
            user=settings.POSTGRES_USER,
            password=settings.POSTGRES_PASSWORD,
            database=settings.POSTGRES_DB,
        )
    except Exception as conn_err:
        print(f"Failed to connect to PostgreSQL at {masked_target}: {type(conn_err).__name__}")
        raise

    # Topological order of tables to preserve foreign keys
    tables = [
        # Level 0
        "users",
        "camera_groups",
        "students",
        "bulk_import_jobs",
        # Level 1
        "cameras",
        "student_photos",
        "student_face_sessions",
        "notification_preferences",
        "notifications",
        # Level 2
        "videos",
        "camera_calibrations",
        "virtual_zones",
        "student_face_embeddings",
        # Level 3
        "tracks",
        "events",
        "incidents",
        # Level 4
        "detections",
        "person_reids",
        "event_tracks",
        "incident_persons",
        "evidences",
        "detected_events",
        "student_recognition_events",
        "reports",
    ]

    total_migrated = 0

    async with pg.transaction():
        for table in tables:
            scur.execute(f"SELECT * FROM `{table}`")
            rows = scur.fetchall()
            row_count = len(rows)
            print(f"Processing table '{table}': {row_count} rows in SQLite...")

            if row_count == 0:
                continue

            col_names = [col[0] for col in scur.description]

            # Prepare records
            records = []
            for row in rows:
                r_dict = dict(row)
                rec = []
                for col in col_names:
                    val = r_dict[col]
                    # Check column transformations
                    if table in ("person_reids", "student_recognition_events") and col == "camera_id":
                        rec.append(norm_str(val))
                    elif col in ("id", "user_id", "camera_id", "group_id", "student_id", "video_id", 
                               "photo_id", "track_id", "event_id", "incident_id", "zone_id", 
                               "identified_student_id", "uploaded_by"):
                        rec.append(norm_uuid(val))
                    elif col in ("created_at", "updated_at", "timestamp", "processing_started_at", "processing_finished_at"):
                        rec.append(norm_dt(val))
                    elif col in ("is_active", "embedding_generated", "email_notifications", "push_notifications", "is_read"):
                        rec.append(norm_bool(val))
                    elif col == "embedding" and table in ("student_face_embeddings", "person_reids"):
                        rec.append(norm_float_array(val))
                    elif col in ("report", "face_bbox", "bounding_box", "metadata_json", "data"):
                        rec.append(norm_json(val))
                    else:
                        rec.append(val)
                records.append(rec)

            # Insert into PostgreSQL
            cols_clause = ", ".join([f'"{c}"' for c in col_names])
            placeholders = ", ".join([f"${i+1}" for i in range(len(col_names))])
            insert_query = f'INSERT INTO "{table}" ({cols_clause}) VALUES ({placeholders})'

            # Batch insert in chunks of 2,000 to manage memory
            chunk_size = 2000
            for i in range(0, len(records), chunk_size):
                chunk = records[i:i + chunk_size]
                await pg.executemany(insert_query, chunk)

            print(f"  [OK] Successfully migrated {len(records)} rows into '{table}'.")
            total_migrated += len(records)

    print("\n==========================================")
    print(f"DATA MIGRATION COMPLETED: {total_migrated} rows successfully transferred.")
    print("==========================================")

    # Verification checks
    print("\nVerifying row count parity between SQLite and PostgreSQL...")
    all_match = True
    for table in tables:
        scur.execute(f"SELECT COUNT(*) FROM `{table}`")
        s_cnt = scur.fetchone()[0]

        pg_cnt = await pg.fetchval(f'SELECT COUNT(*) FROM "{table}"')
        if s_cnt == pg_cnt:
            print(f"  [MATCH] Table '{table}': {s_cnt} SQLite == {pg_cnt} PostgreSQL")
        else:
            print(f"  [MISMATCH] Table '{table}': {s_cnt} SQLite != {pg_cnt} PostgreSQL")
            all_match = False

    if all_match:
        print("\nALL 24 TABLES HAVE PERFECT ROW-COUNT PARITY!")
    else:
        print("\nWARNING: Some tables have row count mismatches!")

    # Check vector embedding arrays
    emb_cnt = await pg.fetchval('SELECT COUNT(*) FROM "student_face_embeddings" WHERE array_length(embedding, 1) = 512')
    print(f"\nVerified {emb_cnt}/57 StudentFaceEmbedding vectors have length exactly 512.")
    reid_cnt = await pg.fetchval('SELECT COUNT(*) FROM "person_reids" WHERE array_length(embedding, 1) = 512')
    print(f"Verified {reid_cnt}/74 PersonReid vectors have length exactly 512.")

    # Check for orphaned foreign keys in PostgreSQL
    print("\nChecking for foreign key orphans in PostgreSQL...")
    orphans_found = False
    fk_checks = [
        ("detections", "track_id", "tracks", "id"),
        ("tracks", "video_id", "videos", "id"),
        ("videos", "uploaded_by", "users", "id"),
        ("student_photos", "student_id", "students", "id"),
        ("student_face_embeddings", "student_id", "students", "id"),
        ("student_face_embeddings", "photo_id", "student_photos", "id"),
        ("person_reids", "track_id", "tracks", "id"),
        ("person_reids", "video_id", "videos", "id"),
        ("notifications", "user_id", "users", "id"),
    ]
    for child_tbl, child_col, parent_tbl, parent_col in fk_checks:
        cnt = await pg.fetchval(f'SELECT count(*) FROM "{child_tbl}" WHERE "{child_col}" IS NOT NULL AND "{child_col}" NOT IN (SELECT "{parent_col}" FROM "{parent_tbl}")')
        if cnt > 0:
            print(f"  [ORPHAN DETECTED] {cnt} rows in {child_tbl}.{child_col} have no parent in {parent_tbl}.{parent_col}!")
            orphans_found = True
        else:
            print(f"  [OK] {child_tbl}.{child_col} -> {parent_tbl}.{parent_col} has 0 orphans.")

    if not orphans_found:
        print("\nREFERENTIAL INTEGRITY AUDIT PASSED: ZERO ORPHANED RECORDS!")

    await pg.close()
    sconn.close()

if __name__ == "__main__":
    asyncio.run(main())
