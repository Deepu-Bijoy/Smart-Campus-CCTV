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

from fastapi.staticfiles import StaticFiles
app.mount("/storage", StaticFiles(directory=settings.STORAGE_DIR), name="storage")

@app.get("/")
async def root():
    return {
        "message": "Welcome to the AI-Powered Smart CCTV Investigation System API.",
        "docs": "/docs"
    }
