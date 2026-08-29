# Development Status

This document tracks the current development status of the AI-Powered Smart Campus Surveillance & Investigation System.

## Completed Modules
- **FastAPI Core & Auth**: Router layers, CORS configurations, Bcrypt password hashing, and JWT token validations.
- **Relational Databases (PostgreSQL)**: SQLAlchemy 2.0 mapping schemas, async engines, and connection pools.
- **Asynchronous Task Workers**: Celery pipeline workers, Redis queue routing, and progress callbacks.
- **Video Ingestion & Metadata Extract**: Multipart upload routes, disk writes, and OpenCV video property parsing.
- **AI Processing Pipeline**:
  - Downsampling video frame reader (5 FPS).
  - YOLOv8 class detector.
  - ByteTrack trajectory association.
  - OpenCV crop exporter.
  - CLIP 512-dimensional semantic embedder.
  - OSNet 512-dimensional person Re-ID signature extractor.
- **Vector DB Indexing (Qdrant)**: CCTV embeddings collection and payload upsert logic.
- **Hybrid Retrieval Engine**: NLP query parses, temporal constraint calculators, and weighted rank scoring algorithms.
- **Search API Layer**: Exposes POST /search, POST /search/explain, and POST /search/similar.
- **AI Weights Caching**: Class-level caching inside CLIPEmbedder to prevent GPU/CPU reload timeouts.
- **Student Management Module**: Exposes CRUD endpoints and photo upload view registries for administrative student enrollment.
- **Face Enrollment Module**: Conversion of student photos into 512-dimensional ArcFace/InsightFace vectors stored in PostgreSQL and Qdrant.
- **Investigation Backend API**: Dynamic timeline builders, dashboard metrics aggregator, and video-specific tracks/detections queries.
- **Real-Time Student Identification Engine**: Pipeline hook and matching service associating person track crops with student identities via Qdrant face vectors.
- **React Investigation Dashboard**: Scaffolded Vite + React 19 + TypeScript + TailwindCSS frontend inside `frontend/` directory with operator views.
- **Camera Management & Virtual Zone Module**: Camera CRUD APIs, PostgreSQL schemas, and interactive React SVG boundary drawing canvas editors.
- **Event Detection Engine**: Trajectory crossing checks, modular zone analyzers, and PostgreSQL event tables.
- **Explainable Adaptive Retrieval Engine**: Multi-channel scoring aggregator (CLIP, OSNet, ArcFace, zone crossings), intent weights adjustments, and graphical explainer panels.
- **AI Investigation Report Generator**: Custom PostgreSQL schemas, report generators (PDF, HTML, JSON download formats), and automated report detail compilation templates.
- **Real-Time Notification & Alert System**: Live WebSocket connections gateway, alert dispatchers mapping severities, floating toast popups, and navbar notification unread badge cards.
- **Production Hardening Phase 1**: Centralized thread-safe singleton `AIModelManager` with FP16 and CUDA warmups, separated Celery task queues (`gpu_queue` and `cpu_queue`), JWT authenticated WebSocket gates, reconnect rate limiting, and socket heartbeat ping-pongs.
- **Bulk Student Import & Bulk Face Enrollment**: CSV/Excel spreadsheet import parser using Pandas, zipped dataset photo matching folders to roll numbers, and asynchronous VRAM-bounded face compilations with ETA calculation and diagnostic reporting logs.
- **Production Hardening Phase 2 (Automatic Local Fallback Mode)**: Graceful automatic fallback configurations to support running the system without Docker. Operates using SQLite + aiosqlite for database schemas, custom SQLAlchemy `TypeDecorator` class to dynamically map arrays to JSON lists, in-memory `QdrantClient(location=":memory:")` for vector stores, and eager/synchronous Celery workflows.

## Modules In Progress
- **Alembic Database Migrations**:
  - *Current Status*: Initial configuration and env.py model registrations are verified. SQLite async-to-sync URI translations are completed for offline compatibility. Migration version scripts are pending generation.

## Pending Modules
- **Crops & Video Streaming APIs**: Endpoints to securely serve crop files and stream video chunks.
- **Incident Reporting & Timeline**: Endpoints to compile tracking histories and export PDF reports.
- **Real-time Alerting Console**: WebSocket gateways to alert operators when anomalies are detected.
- **Frontend Dashboard Application**: React UI web application.

## Future Features
- **Student Face Recognition Module**:
  - Student profile lookups, ArcFace database enrollment, and face verification checks.
  - **Fence Jump Identification**: Anomaly logs checking trajectories against defined boundary polygons.
  - **Fight Participant Verification**: Anomaly checks flagging rapid skeletal velocity shifts (YOLOv8-Pose).
- **GPU Scaling & Triton Server**: Deploying AI models on a dedicated Triton Inference Server to optimize GPU usage.
