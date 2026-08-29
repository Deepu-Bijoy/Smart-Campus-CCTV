# Quick Start Guide

This guide describes the fastest path to launch the **AI-Powered Smart Campus CCTV Surveillance & Investigation System** on a Windows local machine without configuring Docker, remote databases, or Celery queues.

---

## 1. Quick Requirements Check
- **Python**: 3.10 to 3.12 (Python 3.13 requires special care due to build wheel compatibilities for lap/ByteTrack).
- **Node.js**: v18 or later.
- **Hardware**: GPU/CUDA is recommended for real-time video inference, but CPU execution is fully supported as a fallback.

---

## 2. Infrastructure Setup (Local Fallback)
The project comes with **Local Fallback Flags** enabled by default in `backend/.env`. This redirects:
- PostgreSQL ➔ Local SQLite database (`backend/storage/cctv.db`)
- Remote Qdrant ➔ Disk-persistent local Qdrant instance (`backend/storage/qdrant_db`)
- Redis/Celery ➔ Synchronous execution inside the backend process (Celery Always Eager)

This allows you to run the system without Docker.

---

## 3. Backend Setup
Open a **PowerShell** terminal as an administrator, navigate to the `backend` folder, and execute:

```powershell
# Set policy to run script
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Run the environment setup script
.\setup_env.ps1
```
*Note: This script automatically creates a Python virtual environment (`venv`), installs pip dependencies (including PyTorch and Ultralytics), and initializes the SQLite tables.*

### Start Backend
Inside the `backend` folder:
```powershell
# Activate venv
.\venv\Scripts\Activate.ps1

# Start Uvicorn reload server
python -m uvicorn app.main:app --reload
```
The API is now running at: `http://localhost:8000`

---

## 4. Frontend Setup
Open another terminal, navigate to the `frontend` folder, and execute:

```bash
# Install packages
npm install

# Start Vite developer server
npm run dev
```
The Dashboard is now running at: `http://localhost:5173`

---

## 5. First Login
- **URL**: `http://localhost:5173`
- **Default Operator Account**:
  - **Email**: `operator@smartcampus.com`
  - **Password**: `securepassword`
