# Environment Setup Guide (Windows)

This document provides step-by-step instructions to configure your Windows machine from scratch to run the **AI-Powered Smart Campus CCTV Surveillance & Investigation System**.

---

## 1. Prerequisites Setup

### A. Python Installation
1. Download Python **3.10.x** or **3.11.x** from the official [Python Downloads page](https://www.python.org/downloads/). (Avoid Python 3.13 as precompiled binary wheels for custom modules like `lapx` might fail to compile on Windows).
2. Run the installer and check the box to **"Add python.exe to PATH"**.
3. Verify the installation in a new PowerShell window:
   ```powershell
   python --version
   ```

### B. Node.js Installation
1. Download Node.js **v18+** or **v20+ (LTS)** from the official [Node.js page](https://nodejs.org/).
2. Proceed through the installation wizard.
3. Verify installation:
   ```powershell
   node --version
   npm --version
   ```

### C. Docker Desktop Setup (Optional but recommended)
1. Download and install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/).
2. Ensure **WSL 2 backend** is enabled during installation.
3. Start Docker Desktop and verify the CLI is available:
   ```powershell
   docker --version
   docker compose version
   ```

### D. NVIDIA GPU & CUDA Drivers (For Acceleration)
If you have an NVIDIA GPU, install the following to run AI inference on GPU:
1. Install the latest [NVIDIA Game Ready / Studio Drivers](https://www.nvidia.com/Download/index.aspx).
2. Install [CUDA Toolkit 11.8](https://developer.nvidia.com/cuda-11-8-0-download-archive) or [CUDA Toolkit 12.1](https://developer.nvidia.com/cuda-downloads).
3. Install matching [cuDNN libraries](https://developer.nvidia.com/cudnn).
4. Verify CUDA is active by running:
   ```powershell
   nvcc --version
   ```

---

## 2. Setting Up Backend

Navigate into the `backend/` directory of the project:
```powershell
cd "backend"
```

We provide a PowerShell script `setup_env.ps1` that automates creating the virtual environment, configuring path variables, resolving pip, and downloading model checkpoints. 

Run the setup script inside an **Administrator PowerShell Window**:
```powershell
# Temporarily bypass execution script policy
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

# Run environment setup
.\setup_env.ps1
```

### Manual Backend Setup (If script is bypassed)
If you prefer configuring the environment manually:
```powershell
# 1. Create Python virtual environment
python -m venv venv

# 2. Activate virtual environment
.\venv\Scripts\Activate.ps1

# 3. Upgrade pip package installer
python -m pip install --upgrade pip

# 4. Install PyTorch with GPU CUDA support (11.8 / 12.1)
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118

# 5. Install basic pip package requirements
pip install -r requirements.txt

# 6. Install custom packages from Git repository sources
pip install git+https://github.com/KaiyangZhou/deep-person-reid.git
```

---

## 3. Configuring Database & Environment Variables

Inside the `backend/` directory:
1. Make a copy of `.env.example` and rename it to `.env`:
   ```powershell
   copy .env.example .env
   ```
2. By default, the `.env` has fallback flags enabled:
   ```ini
   DB_FALLBACK_SQLITE=true
   QDRANT_IN_MEMORY=true
   CELERY_ALWAYS_EAGER=true
   ```
   *If these flags are set to `true`, you do NOT need to install or start PostgreSQL, Qdrant, or Redis services manually. The system will store data in SQLite under `backend/storage/cctv.db` and index vectors inside a disk-persistent folder `backend/storage/qdrant_db`.*

3. If you want to use the full production docker infrastructure, set these flags to `false` and start Docker Compose:
   ```powershell
   docker compose up -d
   ```

---

## 4. Setting Up Frontend

Navigate into the `frontend/` directory:
```powershell
cd ../frontend
```

Install packages and dependencies:
```powershell
npm install
```

---

## 5. Verification Check

To confirm that the backend and pipeline dependencies are installed correctly, run:
```powershell
cd ../backend
.\venv\Scripts\python.exe verify_deps.py
```
This script checks the availability of PyTorch, OpenCV, InsightFace, ByteTrack, Torchreid, and CLIP configurations, indicating if any component is missing.
