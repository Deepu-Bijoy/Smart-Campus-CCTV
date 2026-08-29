# Changelog

All notable changes to the AI-Powered Smart Campus Surveillance & Investigation System are recorded in this file.

## [2026-07-08]
### Automatic Local Fallback Mode
- **Module**: System Hardening (Production Phase 2).
- **Changes**:
  - Implemented automatic database fallback: if `DB_FALLBACK_SQLITE=true` or if PostgreSQL is unreachable, the system automatically uses SQLite (`sqlite+aiosqlite:///./storage/cctv.db`) without crashing.
  - Implemented custom `SqliteCompatibleArray` mapping using SQLAlchemy `TypeDecorator` to transparently compile PostgreSQL native `ARRAY` columns to `JSON` representations on SQLite on model-load.
  - Implemented in-memory Qdrant fallback: if `QDRANT_IN_MEMORY=true` or if Qdrant is unreachable, the system automatically instantiates an in-memory client (`location=":memory:"`).
  - Implemented eager Celery fallback: if `CELERY_ALWAYS_EAGER=true` or if Redis is unreachable, Celery defaults to eager mode.
  - Updated environment settings to read and alias all fallback configurations from the centralized `Settings` class using Pydantic fields.
  - Updated Alembic migrations configuration to automatically translate `sqlite+aiosqlite://` async URLs to `sqlite://` sync URLs for offline migration operations.
- **Files Modified**:
  - [config.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/core/config.py)
  - [session.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/db/session.py)
  - [base_class.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/db/base_class.py)
  - [env.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/db/migrations/env.py)
  - [.env](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/.env)
- **Reason**: Stabilize local workspace runs by introducing a fallback mode that allows running and testing the entire system without Docker.

## [2026-07-05]
### Bulk Student Import & Bulk Face Enrollment
- **Module**: Student Management (Milestone 12).
- **Changes**: Created `BulkImportJob` database entity, validation schemas, and Celery background task `bulk_enroll_faces_task` supporting ETA tracking, cancellations, and Qdrant indexing. Developed REST endpoints (`POST /import`, `POST /import/photos`, `POST /import/enroll`, `GET /import/status/{job_id}`, `GET /import/report/{job_id}`). Built frontend `BulkImport.tsx` drag-and-drop dashboard.
- **Files Created**:
  - [F23_BulkEnrollment.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F23_BulkEnrollment.md)
  - [bulk_import.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/bulk_import.py)
  - [bulk_import.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/schemas/bulk_import.py)
  - [bulk_tasks.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/tasks/bulk_tasks.py)
  - [import_students.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/import_students.py)
  - [BulkImport.tsx](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/frontend/src/pages/BulkImport.tsx)
- **Reason**: Enable bulk registration and photo processing pipelines.

### Production Hardening Phase 1
- **Module**: System Hardening (Production Phase 1).
- **Changes**: Created `AIModelManager` registry in `core/model_manager.py` with double-checked locking singleton cache, automatic CUDA context detection, FP16 half support, and pre-loading warmups. Refactored YOLO, CLIP, OSNet, and InsightFace pipeline importers to retrieve weights from the central manager. Partitioned Celery task queues into `gpu_queue` and `cpu_queue` in `cel_app.py`. Added token handshake query/header checks, client IP reconnect rate limits, and heartbeat ping-pongs inside WebSocket router gateway `/notifications/ws`.
- **Files Created**:
  - [F22_ProductionHardening_Phase1.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F22_ProductionHardening_Phase1.md)
  - [model_manager.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/core/model_manager.py)
  - [cpu_tasks.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/tasks/cpu_tasks.py)
  - [test_production_hardening.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/test_production_hardening.py)
- **Reason**: Stabilize GPU execution and restrict unauthorized access to real-time notification alerts channels.

### Real-Time Notification & Alerts
- **Module**: Alerts Management (Milestone 11).
- **Changes**: Created notification models (`Notification`, `NotificationPreference`) in `models/notification.py` and validation schemas in `schemas/notification.py`. Implemented connection managers in `notification_service.py` and alert dispatch filters in `alert_dispatcher.py`. Added websocket endpoint `/notifications/ws` and CRUD routers inside `api/v1/notifications.py`. Integrated frontend `NotificationPanel.tsx` in user navigation headers.
- **Files Created**:
  - [F21_RealTimeNotificationAlerts.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F21_RealTimeNotificationAlerts.md)
  - [notification.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/notification.py)
  - [notification.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/schemas/notification.py)
  - [notifications.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/notifications.py)
  - [notification_service.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/services/notification_service.py)
  - [alert_dispatcher.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/services/alert_dispatcher.py)
  - [NotificationPanel.tsx](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/frontend/src/components/NotificationPanel.tsx)
- **Reason**: Implement Milestone 11 to support real-time WebSocket security broadcasts.

### AI Investigation Report Generator
- **Module**: Report Generation (Milestone 10).
- **Changes**: Created report model (`Report`) in `models/report.py` and validation schemas in `schemas/report.py`. Implemented report generation APIs inside `api/v1/reports.py`. Added downloadable formats (HTML, PDF, JSON). Built frontend pages (`Reports.tsx`, `ReportDetails.tsx`) and registered links.
- **Files Created**:
  - [F20_AIInvestigationReportGenerator.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F20_AIInvestigationReportGenerator.md)
  - [report.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/report.py)
  - [report.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/schemas/report.py)
  - [reports.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/reports.py)
  - [Reports.tsx](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/frontend/src/pages/Reports.tsx)
  - [ReportDetails.tsx](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/frontend/src/pages/ReportDetails.tsx)
- **Reason**: Implement Milestone 10 to support security operator report compilers.

### Explainable Adaptive Retrieval
- **Module**: Explainable Search (Milestone 9).
- **Changes**: Created `explanation_engine.py` scoring aggregator resolving ArcFace, OSNet, CLIP, temporal, and zone weights. Updated `query_parser.py` and `ranking.py` to support intent-driven adaptive weights. Updated search controller (`api/v1/search.py`) endpoints `/search/explain` and `/search/evidence/{track_id}`. Upgraded frontend search UI (`Search.tsx`) with side Explanation Panels and graphical breakdown gauges.
- **Files Created**:
  - [F19_ExplainableAdaptiveRetrieval.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F19_ExplainableAdaptiveRetrieval.md)
  - [explanation_engine.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/services/explanation_engine.py)
- **Reason**: Implement Milestone 9 to support interactive explainable retrieval match parameters.

### Event Detection Engine
- **Module**: Event Analysis (Milestone 8).
- **Changes**: Created event models (`Event`, `EventTrack`) in `models/event.py`. Added validation schemas in `schemas/event.py`. Implemented event analysis logic including `zone_analyzer.py`, `trajectory_analyzer.py`, and `event_dispatcher.py` inside `event_engine/`. Built frontend pages (`Events.tsx`, `EventDetails.tsx`) to show incident listings.
- **Files Created**:
  - [F18_EventDetectionEngine.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F18_EventDetectionEngine.md)
  - [event.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/event.py)
  - [event.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/schemas/event.py)
  - [events.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/events.py)
  - [Events.tsx](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/frontend/src/pages/Events.tsx)
  - [EventDetails.tsx](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/frontend/src/pages/EventDetails.tsx)
  - All files in `backend/app/event_engine/`
- **Reason**: Implement Milestone 8 to execute spatial crossing rule evaluations.

### Camera Management & Virtual Zones
- **Module**: Camera & Boundary Management (Milestone 7).
- **Changes**: Created camera models (`Camera`, `CameraGroup`, `CameraCalibration`, `VirtualZone`) in `models/camera.py`. Added validation schemas in `schemas/camera.py`. Implemented camera management REST APIs in `api/v1/cameras.py` and registered the router in `main.py`. Built frontend pages (`Cameras.tsx`, `CameraDetails.tsx`, `VirtualZoneEditor.tsx`) to draw polygon and line boundaries.
- **Files Created**:
  - [F17_CameraManagement.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F17_CameraManagement.md)
  - [camera.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/camera.py)
  - [camera.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/schemas/camera.py)
  - [cameras.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/cameras.py)
  - [Cameras.tsx](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/frontend/src/pages/Cameras.tsx)
  - [CameraDetails.tsx](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/frontend/src/pages/CameraDetails.tsx)
  - [VirtualZoneEditor.tsx](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/frontend/src/components/VirtualZoneEditor.tsx)
- **Reason**: Implement Milestone 7 to support camera catalog indexes and virtual boundary polygon drawing editor.

### React Operator & Investigation Dashboard
- **Module**: Frontend Dashboard (Milestone 6).
- **Changes**: Scaffolded Vite + React 19 + TypeScript + TailwindCSS frontend inside `frontend/` directory. Created modular UI layout widgets (Navbar, Sidebar, VideoPlayer, SearchBar, Timeline, StudentCard, DetectionCard, ProcessingStatus). Built operator views (Login, Dashboard, Videos, Upload, Students, StudentDetails, Search, TimelinePage, Settings) and hooked them to backend APIs with Axios request/response JWT interceptors.
- **Files Created**:
  - [F16_InvestigationDashboard.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F16_InvestigationDashboard.md)
  - All files in `frontend/src/` including components, pages, stores, and styles.
- **Reason**: Implement Milestone 6 to provide campus operators with a functional UI for tracking targets.

### Real-Time Student Identification Engine
- **Module**: Student Identification (Milestone 5).
- **Changes**: Created student face matching service `student_identifier.py` to identify faces in person crops using Qdrant. Hooked identification into video processing orchestrator Stage 6. Created `student_recognition_events` table and appearances/identified REST APIs.
- **Files Modified**:
  - [orchestrator.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/pipeline/orchestrator.py)
  - [investigations.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/investigations.py)
  - [config.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/core/config.py)
  - [env.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/db/migrations/env.py)
  - [recognition.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/recognition.py) [NEW]
  - [recognition.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/schemas/recognition.py) [NEW]
  - [student_identifier.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/services/student_identifier.py) [NEW]
  - [F15_StudentRecognition.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F15_StudentRecognition.md) [NEW]
- **Reason**: Implement Milestone 5 to dynamically verify student identities across CCTV person tracks.

### Investigation Backend APIs
- **Module**: Investigation API (Milestone 4).
- **Changes**: Created new investigations router file `investigations.py` under `api/v1` and added dynamic timeline builders, dashboard metrics aggregator, and video-specific tracks/detections endpoints.
- **Files Modified**:
  - [main.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/main.py)
  - [investigations.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/investigations.py) [NEW]
  - [investigation.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/schemas/investigation.py) [NEW]
  - [F14_InvestigationAPI.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F14_InvestigationAPI.md) [NEW]
- **Reason**: Implement Milestone 4 to expose investigation search parameters and dashboard reports.

### Face Enrollment Engine & Status APIs
- **Module**: Student Face Enrollment (Milestone 3).
- **Changes**: Configured lazy-loaded InsightFace FaceAnalysis engine utilizing Buffalo_L pretrained models. Added blur detection (Laplacian variance), bounding box constraint filters, and duplicate embedding checks in Qdrant. Implemented POST `/students/{id}/enroll` and GET `/students/{id}/enrollment-status`.
- **Files Modified**:
  - [vector_store.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/services/vector_store.py)
  - [students.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/students.py)
  - [student.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/schemas/student.py)
  - [env.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/db/migrations/env.py)
  - [face_embedding.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/face_embedding.py) [NEW]
  - [face_engine.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/pipeline/face_engine.py) [NEW]
  - [F13_FaceEnrollment.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F13_FaceEnrollment.md) [NEW]
  - [PROJECT_ARCHITECTURE.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/PROJECT_ARCHITECTURE.md) [NEW]
- **Reason**: Implement Milestone 3 to extract and index searchable student face embedding vectors.

### Student Management Module Setup
- **Module**: Student Management (Milestone 2).
- **Changes**: Created student schemas, models, API routers, and photo directory management routes under `/api/v1/students`. Exposes registration, paginated search/sorting/filtering, update, cascade delete, and MD5 duplicate checks on multi-photo uploads.
- **Files Modified**:
  - [main.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/main.py)
  - [env.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/db/migrations/env.py)
  - [student.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/student.py) [NEW]
  - [student.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/schemas/student.py) [NEW]
  - [students.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/students.py) [NEW]
  - [F12_StudentManagement.md](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/docs/FEATURES/F12_StudentManagement.md) [NEW]
- **Reason**: Implement Milestone 2 to track student profiles and photo enrollment metadata on the local filesystem.

### Search API Layer & Model Caching Setup
- **Module**: Search API Layer & Deep Learning Pipeline.
- **Changes**: Configured request/response validation schemas, added `POST /search`, `POST /search/explain`, and `POST /search/similar` API routers, registered routers in `main.py`, and implemented class-level caching for model weights in `CLIPEmbedder`.
- **Files Modified**:
  - [main.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/main.py)
  - [search.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/search.py)
  - [search.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/schemas/search.py)
  - [embedder.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/pipeline/embedder.py)
- **Reason**: Implement Milestone 1 search features, support user query explanations, track similarity queries, and optimize API latency by caching model loading.

### Core FastAPI & Auth Setup
- **Module**: API Core & Security.
- **Changes**: Configured application configurations, setup password hashing using Bcrypt, and implemented JWT validation.
- **Files Modified**:
  - [config.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/core/config.py)
  - [security.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/core/security.py)
  - [deps.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/deps.py)
  - [auth.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/auth.py)
  - [user.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/user.py)
- **Reason**: Establish authentication systems to secure endpoints.

### PostgreSQL & Qdrant Models
- **Module**: Database Layer.
- **Changes**: Configured base models, session engines, and tables mapping users, videos, tracks, detections, and person ReIDs.
- **Files Modified**:
  - [session.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/db/session.py)
  - [base_class.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/db/base_class.py)
  - [video.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/video.py)
  - [track.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/models/track.py)
- **Reason**: Enable persistent relational and vector storage.

### Video Ingestion & Metadata Extract
- **Module**: Video Upload Ingestion.
- **Changes**: Added video upload endpoints and configured OpenCV parsing to extract duration, frame rates, and codec structures.
- **Files Modified**:
  - [videos.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/api/v1/videos.py)
  - [video_metadata.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/services/video_metadata.py)
- **Reason**: Enable operators to upload video assets.

### Celery Background Pipeline
- **Module**: Task Management.
- **Changes**: Integrated Celery configurations and configured Redis message routing for background tasks.
- **Files Modified**:
  - [cel_app.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/tasks/cel_app.py)
  - [video_tasks.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/tasks/video_tasks.py)
  - [orchestrator.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/pipeline/orchestrator.py)
- **Reason**: Asynchronously run hardware-intensive AI pipelines.

### AI Frame Processing Engine
- **Module**: Deep Learning Pipeline.
- **Changes**: Configured frame reader downsamplings (5 FPS), YOLOv8 object detection, ByteTrack tracking, OSNet Re-ID, and CLIP embedding generation.
- **Files Modified**:
  - [video_reader.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/pipeline/video_reader.py)
  - [detector.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/pipeline/detector.py)
  - [tracker.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/pipeline/tracker.py)
  - [reid.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/pipeline/reid.py)
  - [embedder.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/pipeline/embedder.py)
  - [frame_processor.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/pipeline/frame_processor.py)
- **Reason**: Enable automated object detection, tracking, and embedding extraction.

### Vector Storage & Hybrid Retrieval
- **Module**: Vector Database & Retrieval Engine.
- **Changes**: Configured Qdrant vector storage indexing, query parsing, and hybrid score ranking.
- **Files Modified**:
  - [vector_store.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/services/vector_store.py)
  - [query_parser.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/services/query_parser.py)
  - [ranking.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/services/ranking.py)
  - [hybrid_retrieval.py](file:///c:/Users/Asus/OneDrive/Desktop/AI-Powered%20Smart%20CCTV%20Investigation%20System/backend/app/services/hybrid_retrieval.py)
- **Reason**: Build the search backend mapping text prompts to database visual points.
