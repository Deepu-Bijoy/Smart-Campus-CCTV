# Project Handover Document

This document provides a summary of the project state, completed modules, limitations, and future instructions for developers taking over the codebase.

---

## 1. Current Implementation Status

### Completed Modules
- **FastAPI Core & Auth**: Login, token verification, and operator role mappings.
- **Camera Management**: CRUD operations on cameras, groups, and zone allocations.
- **Virtual Zone Editor**: Drawing polygon/line zones directly over camera snapshots in the frontend.
- **Video Processing Pipeline**: Frame extraction, YOLOv8 detection, ByteTrack tracking, Re-ID embedding (OSNet), and CLIP semantic vector creation.
- **Student Enrollment System**: Photo upload, Face embedding computation (ArcFace), and vector sync with Qdrant.
- **Semantic Retrieval**: Text-to-image semantic matching using CLIP.
- **Explainable Scoring Engine**: Custom metric combination (semantic similarity, identity Re-ID, temporal overlap, zone status) to generate reasons for matches.

### Partially Completed / Mocked Modules
- **Security Incident Tables**: The schemas for specific security alerts (like Boundary Crossing and fight indicators) are structured. But in the default pipeline, they are simulated and mapped to generic anomalous Events.
- **Sub-clip Evidence Ingestion**: Currently, the system links the original video file and coordinates as evidence, but automatic ffmpeg/opencv sub-clipping of incident intervals is not yet fully automated in the default ingestion runner.

---

## 2. Known Limitations & Constraints
- **GPU Resource Usage**: Running 4 heavy models (YOLO, CLIP, OSNet, ArcFace) simultaneously requires significant VRAM. On low-spec hardware (less than 4GB GPU), we recommend running on CPU fallback or using short, low-resolution clips.
- **Multi-student tracking overlapping**: If multiple students overlap in close proximity (e.g. crowds), ByteTrack ids can swap, affecting trajectory consistency.
- **SQLite Database Concurrency**: In local fallback mode, using SQLite with aiosqlite can occasionally hit lock timeouts during simultaneous database writes by the worker. Production mode (using PostgreSQL) fully avoids this.

---

## 3. Recommended Next Development Steps

### Step 1: Fully Integrate the Incident Detection Engine
- Refine the zone crossings logic to write directly into `Incident` and `IncidentPerson` tables (as detailed in the approved implementation plan).
- Connect the CLIP search index to detect fights automatically at ingestion time by querying for the semantic phrase `"people fighting"` and inserting instances of `Incident` with `incident_type = 'Fight'`.

### Step 2: Implement Automated Sub-clipping
- Use OpenCV in the background ingestion worker to read the video source, seek to the incident timestamp, and export a 5-second MP4 clip centered around the event. Save it to `storage/evidence/` and link it to the `Evidence` database entries.

### Step 3: Implement Live RTSP Stream Processing
- Extend the `FrameProcessor` to read from live camera RTSP streams (using a buffer queue to prevent lag) and trigger live WebSockets alerts when incidents are detected.
