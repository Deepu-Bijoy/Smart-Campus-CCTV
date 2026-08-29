# How to Start and Run the Project

This guide provides instructions on starting all backend components, databases, queues, and the frontend server. 

Choose either **Method A: Local Development (With Fallbacks - Fast)** or **Method B: Docker Infrastructure (Production)**.

---

## Method A: Local Development (SQLite & Local Qdrant)
This method runs all dependencies embedded inside the Python backend process and SQLite files. You do NOT need Docker Desktop running.

Ensure `.env` in the `backend/` directory contains:
```ini
DB_FALLBACK_SQLITE=true
QDRANT_IN_MEMORY=true
CELERY_ALWAYS_EAGER=true
```

### Terminal 1: Start FastAPI Web Backend
1. Open a PowerShell terminal and navigate to `backend/`.
2. Activate your virtual environment and start Uvicorn:
   ```powershell
   .\venv\Scripts\Activate.ps1
   python -m uvicorn app.main:app --reload
   ```

### Terminal 2: Start React Frontend
1. Open a new PowerShell terminal and navigate to `frontend/`.
2. Start the Vite developer server:
   ```powershell
   npm run dev
   ```

---

## Method B: Docker Production Infrastructure
This runs PostgreSQL, Redis, and Qdrant as background container services. Video processing tasks are handled asynchronously by a background Celery worker.

Ensure `.env` in the `backend/` directory contains:
```ini
DB_FALLBACK_SQLITE=false
QDRANT_IN_MEMORY=false
CELERY_ALWAYS_EAGER=false
```

### Terminal 1: Start Infrastructure Containers
1. Start Docker Desktop on your machine.
2. Open a PowerShell terminal at the project root directory.
3. Start the containers in detached mode:
   ```powershell
   docker compose up -d
   ```
4. Verify the containers are healthy:
   ```powershell
   docker compose ps
   ```
   *This starts Postgres (`localhost:5432`), Redis (`localhost:6379`), and Qdrant (`localhost:6333`).*

### Terminal 2: Apply Database Migrations (First Run Only)
1. Navigate to the `backend/` folder in a PowerShell terminal.
2. Activate the virtual environment and apply migrations using Alembic:
   ```powershell
   .\venv\Scripts\Activate.ps1
   alembic upgrade head
   ```

### Terminal 3: Start FastAPI Web Backend
1. Navigate to `backend/` in a PowerShell terminal.
2. Activate your virtual environment and start Uvicorn:
   ```powershell
   .\venv\Scripts\Activate.ps1
   python -m uvicorn app.main:app --reload
   ```

### Terminal 4: Start Celery Video Worker
1. Navigate to `backend/` in a PowerShell terminal.
2. Activate your virtual environment and launch Celery:
   ```powershell
   .\venv\Scripts\Activate.ps1
   celery -A app.tasks.cel_app worker --loglevel=info -P solo
   ```
   *Note: `-P solo` (or `--pool=solo`) is REQUIRED on Windows because Celery's default prefork pool does not support Windows processes correctly.*

### Terminal 5: Start React Frontend
1. Navigate to `frontend/` in a PowerShell terminal.
2. Start the Vite developer server:
   ```powershell
   npm run dev
   ```

---

## Accessing the Dashboards
Once all components are started:
- **Application Frontend**: `http://localhost:5173`
- **FastAPI OpenAPI Swagger Docs**: `http://localhost:8000/docs`
- **Qdrant Web Console UI**: `http://localhost:6333/dashboard`
- **Postgres Database**: `localhost:5432` (Username: `postgres`, Password: `securepassword`, DB: `cctv_investigation`)
- **Operator Default Login**:
  - Email: `operator@smartcampus.com`
  - Password: `securepassword`
