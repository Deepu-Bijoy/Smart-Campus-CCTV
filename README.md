# AI-Powered Smart Campus CCTV Surveillance & Investigation System

An advanced security and forensic surveillance platform designed for campus-wide monitoring, tracking, and natural-language based incident investigation.

---

## 1. Project Overview
The system enables operators to manage camera channels, upload security feeds, and query CCTV footages using simple, natural-language commands (e.g., *"Did anyone jump over the boundary wall?"* or *"Show the student in the black hoodie"*). Rather than relying on simple metadata or manual review, the platform processes video in real-time, extracts trajectories, matches identities using biometric faces/features, and builds a comprehensive index in a vector database for semantic search.

---

## 2. Key Features
- **Video Ingestion & Processing Pipeline**: Automatically reads frames, performs YOLOv8 detection, tracks paths with ByteTrack, and processes features.
- **Deep Re-Identification (Re-ID)**: Utilizes OSNet to build appearance vectors, enabling matching across multiple cameras even under changing angles and lighting.
- **Biometric Face Recognition**: Runs InsightFace with ArcFace to identify students from visual face crops against the campus registry.
- **Semantic Text/Image Matching**: Uses CLIP to embed frame contents, allowing natural language prompts to locate specific actions or subjects.
- **Explainable Scoring Engine**: Scores search matches based on temporal constraints, Re-ID similarity, semantic relevance, and virtual zone crossings.
- **Virtual Zone Monitoring**: Supports polyline and polygon boundary zones to identify trespass events (e.g. fence jumping).
- **Security Reports & Timelines**: Compiles timelines of track appearances and lets operators export formal investigation reports.
- **Real-Time Notification System**: Notifies operators via WebSockets when virtual zones are crossed or high-severity events are detected.

---

## 3. Technology Stack
### Backend
- **FastAPI**: Modern, asynchronous web framework for Python.
- **SQLAlchemy (SQLAlchemy Asyncio)**: ORM mapper using PostgreSQL/SQLite databases.
- **Alembic**: Migration framework for database version control.
- **Redis & Celery**: Task queue and broker for processing heavy video operations in background workers.
- **Pydantic**: Data validation and setting management.

### AI Models & Computer Vision
- **PyTorch & torchvision**: Underlying deep learning engine.
- **YOLOv8 (Ultralytics)**: Object detection model trained on MS COCO.
- **ByteTrack**: Motion-based multi-object tracking.
- **OSNet (Deep Torchreid)**: Deep Re-ID architecture for person re-identification.
- **ArcFace (InsightFace)**: Deep facial recognition.
- **CLIP (Hugging Face / OpenAI)**: Vision-Language representation model.

### Vector Storage
- **Qdrant**: High-performance vector database used to store and query CLIP frame embeddings and student face vectors.

### Frontend
- **React + TypeScript + Vite**: Responsive client-side UI dashboard.
- **Tailwind CSS**: Utility-first styling framework.
- **TanStack React Query**: State management and API caching.
- **Lucide React**: Vector icons.

---

## 4. Main System Workflows

### A. CCTV Video Ingestion Pipeline
```
[Video Uploaded] ➔ [Frame Reader] ➔ [YOLOv8 Detection] ➔ [ByteTrack Tracking]
                                                                    │
      ┌─────────────────────────────────────────────────────────────┘
      ▼
[Feature Extraction] ➔ [OSNet Re-ID] ➔ [InsightFace / ArcFace] ➔ [CLIP Embedding]
      │
      ├──➔ Save Tracks, Detections, and Crops to PostgreSQL Database
      └──➔ Upsert CLIP vectors and Face embeddings to Qdrant Vector DB
```

### B. Student Face Enrollment Workflow
1. User uploads a student photo profile.
2. InsightFace detects the face, checks quality, and extracts a 512-dimension ArcFace embedding.
3. The embedding is registered in Qdrant's `student_face_embeddings` collection and linked to the SQLite/PostgreSQL `students` table.
4. During video processing, when a person is tracked, the system extracts their face crop, computes the ArcFace vector, and queries Qdrant to identify the student.

### C. Natural Language Forensic Search
1. Operator types a search query (e.g., *"Show the student near the fence after 2:00 PM"*).
2. The **Query Parser** extracts:
   - Target object class (`person`)
   - Intent (`zone` crossing)
   - Temporal constraints (after 2:00 PM)
3. The text query is converted to a vector using the CLIP text encoder.
4. Qdrant searches the `cctv_embeddings` collection using cosine similarity.
5. The **Explanation Engine** calculates:
   - Visual Re-ID similarity (OSNet)
   - Face identification score (ArcFace)
   - Temporal score matching constraints
   - Zone crossing status
6. The system returns the candidate list with detailed confidence ratings and textual reasoning.

---

## 5. Directory Structure
```
.
├── backend/
│   ├── app/
│   │   ├── api/v1/          # FastAPI routers (auth, search, students, etc.)
│   │   ├── core/            # System config, security, and model warmups
│   │   ├── db/              # Database sessions and alembic configurations
│   │   ├── event_engine/    # Trajectory analyzers and zone monitoring
│   │   ├── models/          # SQLAlchemy Database model classes
│   │   ├── pipeline/        # Ingestion pipeline (detector, tracker, reid, clip)
│   │   ├── schemas/         # Pydantic schemas for serialization
│   │   ├── services/        # Logic services (Qdrant store, Re-ID ranker, explanations)
│   │   ├── tasks/           # Celery background tasks
│   │   └── main.py          # FastAPI application entrypoint
│   ├── storage/             # Persistent local data (sqlite DB, model caches, crops)
│   ├── requirements.txt     # Python requirements
│   ├── setup_env.ps1        # Environment installation script
│   └── yolov8n.pt           # Local YOLO weight file
├── docs/                    # Detailed architectural documents
├── frontend/
│   ├── public/              # Static assets
│   ├── src/
│   │   ├── components/      # UI controls (cards, video players, sidebars)
│   │   ├── pages/           # Page routes (search, dashboard, reports, students)
│   │   ├── services/        # Axios API wrapper instances
│   │   └── App.tsx          # Frontend routing configuration
│   ├── package.json         # Node.js dependencies
│   └── vite.config.ts       # Vite config settings
├── docker-compose.yml       # Docker environment configuration
└── README.md                # This file
```

---

## 6. General System Requirements
- **OS**: Windows 10/11 or Ubuntu 20.04+ (Windows setup commands provided in guides).
- **CPU**: Multicore CPU with virtual VT-x enabled.
- **RAM**: Minimum 16 GB (32 GB recommended for loading all models).
- **GPU (Optional)**: NVIDIA GPU with CUDA support for acceleration.
