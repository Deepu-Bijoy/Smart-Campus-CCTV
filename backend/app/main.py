from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.exceptions import setup_exception_handlers
from app.tasks.cel_app import celery_app
from app.api.v1 import auth, videos, health, search, students, investigations, cameras, events, reports, notifications, import_students, violence
 
app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

import logging as _logging
_dep_logger = _logging.getLogger("app.startup.deps")

_PIPELINE_DEPS = [
    # (display_name, import_statement)
    ("torch",              "import torch"),
    ("torchvision",        "import torchvision"),
    ("lap (lapx)",         "import lap"),
    ("ultralytics/YOLO",   "from ultralytics import YOLO"),
    ("supervision",        "import supervision"),
    ("filterpy",           "import filterpy"),
    ("scipy",              "import scipy"),
    ("cv2 (opencv)",       "import cv2"),
    ("insightface",        "import insightface"),
    ("onnxruntime",        "import onnxruntime"),
    ("torchreid",          "import torchreid"),
    ("transformers/CLIP",  "from transformers import CLIPModel"),
    ("qdrant_client",      "import qdrant_client"),
    ("celery",             "import celery"),
    ("fastapi",            "import fastapi"),
    ("sqlalchemy",         "import sqlalchemy"),
]

def _check_pipeline_deps():
    """
    Checks every critical AI pipeline dependency at startup.
    Logs CRITICAL for anything missing so the operator knows
    exactly which package to install — never silently fails.
    """
    print("\n========== PIPELINE DEPENDENCY CHECK ==========")
    missing = []
    for name, stmt in _PIPELINE_DEPS:
        try:
            exec(stmt)
            print(f"  [OK]   {name}")
        except (ImportError, ModuleNotFoundError) as e:
            print(f"  [FAIL] {name} — {e}")
            _dep_logger.critical(
                f"MISSING DEPENDENCY: '{name}' — {e}\n"
                f"  Install it inside the venv: .\\venv\\Scripts\\pip install <package>"
            )
            missing.append(name)

    if missing:
        print(f"\n  CRITICAL: {len(missing)} missing package(s): {', '.join(missing)}")
        print("  Video processing will fail until these are installed.")
        print("  Run: powershell -ExecutionPolicy Bypass -File setup_env.ps1")
    else:
        print("\n  All pipeline dependencies are present.")
    print("================================================\n")


@app.on_event("startup")
async def startup_event():
    if "sqlite" in settings.SQLALCHEMY_DATABASE_URI:
        import os
        import shutil
        import sqlite3

        db_path = "./storage/cctv.db"
        fallback_path = "./storage/sqlite_fallback.db"

        needs_restore = False
        if not os.path.exists(db_path) or os.path.getsize(db_path) == 0:
            needs_restore = True
        else:
            try:
                conn = sqlite3.connect(db_path)
                cursor = conn.cursor()
                cursor.execute("SELECT count(*) FROM users")
                count = cursor.fetchone()[0]
                if count == 0:
                    needs_restore = True
                conn.close()
            except Exception:
                needs_restore = True

        if needs_restore and os.path.exists(fallback_path):
            print(f"Active database '{db_path}' is empty or missing. Restoring template from '{fallback_path}'...")
            os.makedirs(os.path.dirname(db_path), exist_ok=True)
            shutil.copyfile(fallback_path, db_path)
            print("Database template restored successfully.")

        from app.db.base_class import Base
        from app.models.user import User
        from app.models.video import Video
        from app.models.track import Track, Detection, PersonReid
        from app.models.student import Student, StudentPhoto, StudentFaceSession
        from app.models.face_embedding import StudentFaceEmbedding
        from app.models.camera import Camera, VirtualZone
        from app.models.event import Event, EventTrack
        from app.models.report import Report
        from app.models.notification import Notification, NotificationPreference
        from app.models.bulk_import import BulkImportJob
        from app.models.incident import Incident, IncidentPerson, Evidence, DetectedEvent
        from app.db.session import engine
        import sqlalchemy

        print("Initializing tables in local SQLite database...")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            
            try:
                await conn.execute(sqlalchemy.text("ALTER TABLE tracks ADD COLUMN identified_student_id CHAR(32)"))
                print("Database migration: added identified_student_id column to tracks table.")
            except Exception:
                pass
            try:
                await conn.execute(sqlalchemy.text("ALTER TABLE videos ADD COLUMN camera_id CHAR(32)"))
                print("Database migration: added camera_id column to videos table.")
            except Exception:
                pass
            try:
                await conn.execute(sqlalchemy.text("ALTER TABLE students ADD COLUMN embedding_generated BOOLEAN DEFAULT FALSE"))
                print("Database migration: added embedding_generated column to students table.")
            except Exception:
                pass
            try:
                await conn.execute(sqlalchemy.text("ALTER TABLE reports ADD COLUMN incident_id CHAR(36)"))
                print("Database migration: added incident_id column to reports table.")
            except Exception:
                pass
            try:
                await conn.execute(sqlalchemy.text("ALTER TABLE notifications ADD COLUMN dedup_key VARCHAR(255)"))
                print("Database migration: added dedup_key column to notifications table.")
            except Exception:
                pass
            try:
                await conn.execute(sqlalchemy.text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_notifications_user_dedup ON notifications(user_id, dedup_key) WHERE dedup_key IS NOT NULL"
                ))
                print("Database migration: enforced UNIQUE index on notifications(user_id, dedup_key).")
            except Exception:
                pass

            # Migration for FAIL-04: Enforce UNIQUE constraint on reports.incident_id
            try:
                # 1. Verify existing database records: detect duplicate non-null incident_id values
                dup_res = await conn.execute(sqlalchemy.text(
                    "SELECT incident_id, COUNT(*) as cnt FROM reports "
                    "WHERE incident_id IS NOT NULL "
                    "GROUP BY incident_id HAVING COUNT(*) > 1"
                ))
                dups = dup_res.fetchall()
                if dups:
                    dup_details = [(str(d[0]), d[1]) for d in dups]
                    err_msg = (
                        f"FATAL DATABASE INTEGRITY ERROR: Found {len(dups)} duplicate incident_id "
                        f"group(s) in reports table: {dup_details}. Aborting UNIQUE index creation "
                        "without modifying or deleting existing records."
                    )
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)

                # 2. Upgrade non-unique index to UNIQUE index (SQLite and PostgreSQL compatible)
                try:
                    await conn.execute(sqlalchemy.text("DROP INDEX IF EXISTS ix_reports_incident_id"))
                except Exception:
                    pass

                await conn.execute(sqlalchemy.text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_reports_incident_id ON reports(incident_id)"
                ))
                print("Database migration: enforced UNIQUE index ix_reports_incident_id on reports(incident_id).")
            except RuntimeError:
                raise
            except Exception as e:
                print(f"Database migration notice for reports(incident_id) unique index: {e}")

            # Migration for DEFECT-DB-02: Enforce FOREIGN KEY on reports.incident_id -> incidents(id) ON DELETE SET NULL
            try:
                # 1. Audit existing reports for invalid incident_id references before applying constraint
                inv_res = await conn.execute(sqlalchemy.text(
                    "SELECT id, incident_id FROM reports "
                    "WHERE incident_id IS NOT NULL AND incident_id NOT IN (SELECT id FROM incidents)"
                ))
                invalid_reports = inv_res.fetchall()
                if invalid_reports:
                    inv_details = [(str(r[0]), str(r[1])) for r in invalid_reports]
                    err_msg = (
                        f"FATAL DATABASE INTEGRITY ERROR: Found {len(invalid_reports)} report(s) with invalid "
                        f"incident_id references: {inv_details}. Aborting foreign key migration without modifying records."
                    )
                    logger.error(err_msg)
                    raise RuntimeError(err_msg)

                # 2. In SQLite, check if reports table already has foreign key on incident_id
                fk_res = await conn.execute(sqlalchemy.text("PRAGMA foreign_key_list(reports)"))
                fks = fk_res.fetchall()
                has_incident_fk = any(fk[2] == "incidents" and fk[3] == "incident_id" for fk in fks)

                if not has_incident_fk:
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=OFF"))
                    await conn.execute(sqlalchemy.text("""
                        CREATE TABLE reports_new (
                            id CHAR(36) NOT NULL,
                            title VARCHAR(100) NOT NULL,
                            incident_type VARCHAR(50) NOT NULL,
                            incident_id CHAR(36),
                            student_id CHAR(36),
                            created_at DATETIME NOT NULL,
                            data JSON NOT NULL,
                            PRIMARY KEY (id),
                            FOREIGN KEY(student_id) REFERENCES students (id) ON DELETE SET NULL,
                            FOREIGN KEY(incident_id) REFERENCES incidents (id) ON DELETE SET NULL
                        )
                    """))
                    await conn.execute(sqlalchemy.text("""
                        INSERT INTO reports_new (id, title, incident_type, incident_id, student_id, created_at, data)
                        SELECT id, title, incident_type, incident_id, student_id, created_at, data FROM reports
                    """))
                    await conn.execute(sqlalchemy.text("DROP TABLE reports"))
                    await conn.execute(sqlalchemy.text("ALTER TABLE reports_new RENAME TO reports"))
                    await conn.execute(sqlalchemy.text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS ix_reports_incident_id ON reports(incident_id)"
                    ))
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=ON"))
                    print("Database migration: added FOREIGN KEY (incident_id) REFERENCES incidents (id) ON DELETE SET NULL to reports table.")
            except RuntimeError:
                raise
            except Exception as e:
                print(f"Database migration notice for reports foreign key: {e}")
                
            # Create SQL indexes for query optimization
            for idx_name, table, column in [
                ("idx_videos_camera_id", "videos", "camera_id"),
                ("idx_tracks_video_id", "tracks", "video_id"),
                ("idx_detections_track_id", "detections", "track_id"),
                ("idx_person_reid_track_id", "person_reids", "track_id"),
                ("idx_person_reid_video_id", "person_reids", "video_id"),
                ("idx_reports_created_at", "reports", "created_at"),
                ("idx_detected_events_track_id", "detected_events", "track_id"),
                ("idx_incidents_camera_id", "incidents", "camera_id"),
                ("idx_incident_persons_student_id", "incident_persons", "student_id"),
                ("idx_students_name", "students", "name"),
                ("idx_student_recognition_events_student_id", "student_recognition_events", "student_id"),
                ("idx_student_recognition_events_track_id", "student_recognition_events", "track_id")
            ]:
                try:
                    await conn.execute(sqlalchemy.text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({column})"))
                    print(f"Database index migration: created index {idx_name} on {table}({column}).")
                except Exception:
                    pass

            # Legacy student UUID normalization (32-char hex -> 36-char hyphenated canonical UUID)
            try:
                res = await conn.execute(sqlalchemy.text("SELECT id FROM students WHERE length(id) = 32"))
                legacy_students = res.fetchall()
                if legacy_students:
                    print(f"Database UUID migration: found {len(legacy_students)} students with 32-char hex IDs. Normalizing...")
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=OFF"))
                    import uuid as _norm_uuid
                    ref_tables = [
                        ("student_photos", "student_id"),
                        ("student_face_sessions", "student_id"),
                        ("student_face_embeddings", "student_id"),
                        ("events", "student_id"),
                        ("student_recognition_events", "student_id"),
                        ("incident_persons", "student_id"),
                        ("reports", "student_id"),
                        ("tracks", "identified_student_id")
                    ]
                    for (old_id,) in legacy_students:
                        canon_id = str(_norm_uuid.UUID(old_id))
                        await conn.execute(
                            sqlalchemy.text("UPDATE students SET id = :new_id WHERE id = :old_id"),
                            {"new_id": canon_id, "old_id": old_id}
                        )
                        for tbl, col in ref_tables:
                            await conn.execute(
                                sqlalchemy.text(f"UPDATE {tbl} SET {col} = :new_id WHERE {col} = :old_id"),
                                {"new_id": canon_id, "old_id": old_id}
                            )
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=ON"))
                    print(f"Database UUID migration: successfully normalized {len(legacy_students)} students to canonical 36-char format.")
            except Exception as e:
                print(f"Database UUID migration notice: {e}")

            # Legacy camera UUID normalization (32-char hex -> 36-char hyphenated canonical UUID)
            try:
                c_res = await conn.execute(sqlalchemy.text("SELECT id FROM cameras WHERE length(id) = 32"))
                legacy_cameras = c_res.fetchall()
                if legacy_cameras:
                    print(f"Database Camera UUID migration: found {len(legacy_cameras)} cameras with 32-char hex IDs. Normalizing...")
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=OFF"))
                    import uuid as _norm_cam_uuid
                    camera_ref_tables = [
                        ("videos", "camera_id"),
                        ("camera_calibrations", "camera_id"),
                        ("virtual_zones", "camera_id"),
                        ("events", "camera_id"),
                        ("student_recognition_events", "camera_id"),
                        ("incidents", "camera_id"),
                        ("detected_events", "camera_id")
                    ]
                    for (old_id,) in legacy_cameras:
                        canon_id = str(_norm_cam_uuid.UUID(old_id))
                        for tbl, col in camera_ref_tables:
                            await conn.execute(
                                sqlalchemy.text(f"UPDATE {tbl} SET {col} = :new_id WHERE {col} = :old_id"),
                                {"new_id": canon_id, "old_id": old_id}
                            )
                        await conn.execute(
                            sqlalchemy.text("UPDATE cameras SET id = :new_id WHERE id = :old_id"),
                            {"new_id": canon_id, "old_id": old_id}
                        )
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=ON"))
                    print(f"Database Camera UUID migration: successfully normalized {len(legacy_cameras)} cameras to canonical 36-char format.")
            except Exception as e:
                print(f"Database Camera UUID migration notice: {e}")

            # Legacy video UUID and uploaded_by normalization (32-char hex -> 36-char hyphenated canonical UUID)
            try:
                v_res = await conn.execute(sqlalchemy.text("SELECT id FROM videos WHERE length(id) = 32"))
                legacy_videos = v_res.fetchall()
                if legacy_videos:
                    print(f"Database Video UUID migration: found {len(legacy_videos)} videos with 32-char hex IDs. Normalizing...")
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=OFF"))
                    import uuid as _norm_vid_uuid
                    video_ref_tables = [
                        ("tracks", "video_id"),
                        ("person_reids", "video_id"),
                        ("events", "video_id"),
                        ("student_recognition_events", "video_id"),
                        ("detected_events", "video_id")
                    ]
                    for (old_id,) in legacy_videos:
                        canon_id = str(_norm_vid_uuid.UUID(old_id))
                        for tbl, col in video_ref_tables:
                            await conn.execute(
                                sqlalchemy.text(f"UPDATE {tbl} SET {col} = :new_id WHERE {col} = :old_id"),
                                {"new_id": canon_id, "old_id": old_id}
                            )
                        await conn.execute(
                            sqlalchemy.text("UPDATE videos SET id = :new_id WHERE id = :old_id"),
                            {"new_id": canon_id, "old_id": old_id}
                        )
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=ON"))
                    print(f"Database Video UUID migration: successfully normalized {len(legacy_videos)} videos to canonical 36-char format.")
            except Exception as e:
                print(f"Database Video UUID migration notice: {e}")

            try:
                u_res = await conn.execute(sqlalchemy.text("SELECT uploaded_by FROM videos WHERE length(uploaded_by) = 32 GROUP BY uploaded_by"))
                legacy_uploaders = u_res.fetchall()
                if legacy_uploaders:
                    print(f"Database Video uploaded_by migration: found {len(legacy_uploaders)} distinct 32-char hex uploaders. Normalizing...")
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=OFF"))
                    import uuid as _norm_u_uuid
                    for (old_u_id,) in legacy_uploaders:
                        canon_u_id = str(_norm_u_uuid.UUID(old_u_id))
                        await conn.execute(
                            sqlalchemy.text("UPDATE videos SET uploaded_by = :new_id WHERE uploaded_by = :old_id"),
                            {"new_id": canon_u_id, "old_id": old_u_id}
                        )
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=ON"))
                    print(f"Database Video uploaded_by migration: successfully normalized {len(legacy_uploaders)} uploaders to canonical 36-char format.")
            except Exception as e:
                print(f"Database Video uploaded_by migration notice: {e}")

            # Legacy incident UUID normalization (32-char hex -> 36-char hyphenated canonical UUID)
            try:
                inc_res = await conn.execute(sqlalchemy.text("SELECT id FROM incidents WHERE length(id) = 32"))
                legacy_incidents = inc_res.fetchall()
                if legacy_incidents:
                    print(f"Database Incident UUID migration: found {len(legacy_incidents)} incidents with 32-char hex IDs. Normalizing...")
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=OFF"))
                    import uuid as _norm_inc_uuid
                    inc_ref_tables = [
                        ("incident_persons", "incident_id"),
                        ("evidences", "incident_id"),
                        ("detected_events", "incident_id"),
                        ("reports", "incident_id")
                    ]
                    for (old_id,) in legacy_incidents:
                        canon_id = str(_norm_inc_uuid.UUID(old_id))
                        for tbl, col in inc_ref_tables:
                            await conn.execute(
                                sqlalchemy.text(f"UPDATE {tbl} SET {col} = :new_id WHERE {col} = :old_id"),
                                {"new_id": canon_id, "old_id": old_id}
                            )
                        await conn.execute(
                            sqlalchemy.text("UPDATE incidents SET id = :new_id WHERE id = :old_id"),
                            {"new_id": canon_id, "old_id": old_id}
                        )
                    await conn.execute(sqlalchemy.text("PRAGMA foreign_keys=ON"))
                    print(f"Database Incident UUID migration: successfully normalized {len(legacy_incidents)} incidents to canonical 36-char format.")
            except Exception as e:
                print(f"Database Incident UUID migration notice: {e}")

        print("SQLite fallback tables initialized successfully.")

        # Sync database face embeddings to Qdrant
        try:
            from app.services.vector_store import QdrantVectorStore
            qdrant_store = QdrantVectorStore()
            
            # Create Qdrant Payload indexes
            try:
                from qdrant_client.http.models import PayloadSchemaType
                for collection in ["cctv_embeddings", "student_face_embeddings"]:
                    for field in ["camera_id", "video_id", "track_id", "object_class", "student_id", "event_type", "timestamp"]:
                        try:
                            qdrant_store.client.create_payload_index(
                                collection_name=collection,
                                field_name=field,
                                field_schema=PayloadSchemaType.KEYWORD
                            )
                        except Exception:
                            pass
                print("Qdrant payload indexes optimized successfully.")
            except Exception:
                pass
                
            if settings.QDRANT_IN_MEMORY:
                print("Syncing database face embeddings to in-memory Qdrant...")
                from sqlalchemy.future import select
                from app.models.face_embedding import StudentFaceEmbedding
                from app.models.student import Student
                from app.db.session import SessionLocal
                
                async with SessionLocal() as db_session:
                    stmt = select(StudentFaceEmbedding)
                    res = await db_session.execute(stmt)
                    embeddings = res.scalars().all()
                    
                    if embeddings:
                        for emb in embeddings:
                            std_res = await db_session.execute(select(Student).filter(Student.id == emb.student_id))
                            student = std_res.scalars().first()
                            
                            payload = {
                                "student_id": str(emb.student_id),
                                "photo_id": str(emb.photo_id),
                                "quality": emb.quality_score,
                                "department": student.department if student else "Unknown",
                                "year": student.year if student else 0
                            }
                            qdrant_store.upsert_face_embedding(
                                embedding_id=emb.id,
                                vector=emb.embedding,
                                payload=payload
                            )
                        print(f"Successfully synced {len(embeddings)} face embeddings to in-memory Qdrant.")
                    else:
                        print("No face embeddings in database to sync.")
        except Exception as e:
            print(f"Warning: face embeddings synchronization to Qdrant failed: {str(e)}")

    print("--- REGISTERED ROUTES ---")
    for route in app.routes:
        if hasattr(route, "path"):
            print(route.path)
        elif hasattr(route, "original_router") and hasattr(route.original_router, "routes"):
            # Extract paths from included sub-routers
            prefix = ""
            if hasattr(route, "include_context") and route.include_context:
                prefix = getattr(route.include_context, "prefix", "")
            for sub_route in route.original_router.routes:
                if hasattr(sub_route, "path"):
                    print(f"{prefix}{sub_route.path}")
    print("-------------------------")

    # ── Pipeline dependency validation ─────────────────────────────────
    # Run before model warmup so operators see exactly what's missing.
    _check_pipeline_deps()

    try:
        from app.core.model_manager import model_manager
        model_manager.warmup_all_models()
    except Exception as e:
        print(f"Warning: model warmup skipped or failed: {str(e)}") 

import time
import logging
from fastapi import Request

request_logger = logging.getLogger("app.request_logger")
request_logger.setLevel(logging.INFO)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    path = request.url.path
    method = request.method
    
    # Try to find matched route path in FastAPI app routes
    matched_route = "None"
    for r in request.app.routes:
        try:
            match, _ = r.matches(request.scope)
            if match.name == "FULL" or getattr(match, "value", 0) == 2:
                matched_route = f"{r.path}"
                break
        except Exception:
            pass
            
    request_logger.info(f"--> Request: {method} {path} | Matched Route: {matched_route}")
    
    start_time = time.time()
    try:
        response = await call_next(request)
        process_time = (time.time() - start_time) * 1000
        request_logger.info(f"<-- Response: {method} {path} | Status: {response.status_code} | Time: {process_time:.2f}ms")
        return response
    except Exception as e:
        process_time = (time.time() - start_time) * 1000
        request_logger.error(f"<-- Exception: {method} {path} | Error: {str(e)} | Time: {process_time:.2f}ms", exc_info=True)
        raise e

# CORS configuration
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Setup custom exception handlers
setup_exception_handlers(app)

# Include API Routers
app.include_router(health.router, prefix=f"{settings.API_V1_STR}/health", tags=["Health"])
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication"])
app.include_router(videos.router, prefix=f"{settings.API_V1_STR}/videos", tags=["Videos"])
app.include_router(search.router, prefix=f"{settings.API_V1_STR}/search", tags=["Search"])
app.include_router(import_students.router, prefix=f"{settings.API_V1_STR}/students", tags=["Bulk Import"])
app.include_router(students.router, prefix=f"{settings.API_V1_STR}/students", tags=["Students"])
app.include_router(cameras.router, prefix=f"{settings.API_V1_STR}/cameras", tags=["Cameras"])
app.include_router(events.router, prefix=f"{settings.API_V1_STR}/events", tags=["Events"])
app.include_router(reports.router, prefix=f"{settings.API_V1_STR}/reports", tags=["Reports"])
app.include_router(notifications.router, prefix=f"{settings.API_V1_STR}/notifications", tags=["Notifications"])
app.include_router(investigations.router, prefix=f"{settings.API_V1_STR}", tags=["Investigations"])
app.include_router(violence.router, prefix=f"{settings.API_V1_STR}/violence", tags=["Violence Detection"])

import os
import jwt
from typing import Optional
from fastapi import Header, Query, HTTPException, status
from fastapi.responses import FileResponse
from app.core import security

@app.get("/storage/{file_path:path}")
async def get_protected_storage_file(
    file_path: str,
    authorization: Optional[str] = Header(None),
    token: Optional[str] = Query(None)
):
    """
    Secure file access for surveillance media assets.
    Requires authentication via Authorization header or ?token= query parameter.
    Blocks access to raw database files, model weights, and system configs.
    """
    raw_token = token
    if not raw_token and authorization and authorization.startswith("Bearer "):
        raw_token = authorization.split("Bearer ", 1)[1]
    
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to access storage assets"
        )
    
    try:
        jwt.decode(raw_token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if security.is_token_revoked(raw_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has been revoked"
            )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired authentication credentials"
        )

    # Strictly block system, database, and neural model files
    blocked_exts = {".db", ".sqlite", ".sqlite3", ".pt", ".onnx", ".env", ".py", ".json", ".sh", ".key"}
    ext = os.path.splitext(file_path)[1].lower()
    if ext in blocked_exts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access to database, model, or configuration files is strictly forbidden"
        )

    abs_storage = os.path.abspath(settings.STORAGE_DIR)
    target_file = os.path.abspath(os.path.join(abs_storage, file_path))
    if os.path.commonpath([abs_storage, target_file]) != abs_storage or not os.path.exists(target_file):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Requested file not found"
        )

    return FileResponse(target_file)


@app.get("/")
async def root():
    return {
        "message": "Welcome to the AI-Powered Smart CCTV Investigation System API.",
        "docs": "/docs"
    }
