# setup_env.ps1
# AI-Powered Smart CCTV Investigation System - Environment Setup
# Usage: powershell -ExecutionPolicy Bypass -File setup_env.ps1

$ErrorActionPreference = "Stop"
$OFFICIAL_PYTHON = "C:\Users\Asus\AppData\Local\Programs\Python\Python313\python.exe"
$VENV_DIR = ".\venv"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " AI CCTV System - Environment Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/7] Validating Python installation..." -ForegroundColor Yellow
if (-not (Test-Path $OFFICIAL_PYTHON)) {
    Write-Host "ERROR: Official python.org Python 3.13 not found at $OFFICIAL_PYTHON" -ForegroundColor Red
    Write-Host "Download: https://www.python.org/downloads/windows/" -ForegroundColor Yellow
    exit 1
}
$pythonPath = & $OFFICIAL_PYTHON -c "import sys; print(sys.executable)"
if ($pythonPath -like "*WindowsApps*" -or $pythonPath -like "*Microsoft*") {
    Write-Host "ERROR: Microsoft Store Python detected. Must use official installer." -ForegroundColor Red
    exit 1
}
$pythonVersion = & $OFFICIAL_PYTHON --version
Write-Host "  OK: $pythonVersion at $pythonPath" -ForegroundColor Green

Write-Host ""
Write-Host "[2/7] Creating virtual environment in $VENV_DIR ..." -ForegroundColor Yellow
if (Test-Path "$VENV_DIR\Scripts\python.exe") {
    Write-Host "  Removing existing venv..." -ForegroundColor DarkYellow
    Remove-Item -Recurse -Force $VENV_DIR
}
& $OFFICIAL_PYTHON -m venv $VENV_DIR
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: Failed to create venv." -ForegroundColor Red; exit 1 }
$VENV_PYTHON = ".\venv\Scripts\python.exe"
$VENV_PIP = ".\venv\Scripts\pip.exe"
$venvVer = & $VENV_PYTHON --version
Write-Host "  OK: venv created - $venvVer" -ForegroundColor Green

Write-Host ""
Write-Host "[3/7] Upgrading pip, setuptools, wheel, Cython..." -ForegroundColor Yellow
& $VENV_PYTHON -m pip install --upgrade pip setuptools wheel Cython --quiet
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: pip upgrade failed." -ForegroundColor Red; exit 1 }
Write-Host "  OK: pip upgraded." -ForegroundColor Green

Write-Host ""
Write-Host "[4/7] Installing PyTorch + torchvision (CUDA 12.4 - for Python 3.13)..." -ForegroundColor Yellow
Write-Host "  Downloading ~2.5 GB. This may take several minutes..." -ForegroundColor DarkYellow
& $VENV_PIP install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: PyTorch install failed." -ForegroundColor Red; exit 1 }
$cudaResult = & $VENV_PYTHON -c "import torch; avail = torch.cuda.is_available(); dev = torch.cuda.get_device_name(0) if avail else 'None'; print('CUDA:', avail, '| GPU:', dev)"
Write-Host "  OK: PyTorch installed. $cudaResult" -ForegroundColor Green

Write-Host ""
Write-Host "[5/7] Installing lapx (ByteTrack LAP solver)..." -ForegroundColor Yellow
& $VENV_PIP install lapx
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: lapx install failed." -ForegroundColor Red; exit 1 }
$lapResult = & $VENV_PYTHON -c "import lap; print(lap.__version__)"
Write-Host "  OK: lapx installed - lap module version: $lapResult" -ForegroundColor Green

Write-Host ""
Write-Host "[6/7] Installing all backend requirements..." -ForegroundColor Yellow
& $VENV_PIP install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Host "ERROR: requirements.txt install failed." -ForegroundColor Red; exit 1 }
Write-Host "  OK: Core requirements installed." -ForegroundColor Green

# torchreid does not support pip install on Python 3.13 (setup.py imports fail).
# Solution: clone and copy the package directory directly into site-packages.
Write-Host "  Installing torchreid (manual copy for Python 3.13 compatibility)..." -ForegroundColor DarkYellow
$torchreidSrc = ".\venv\torchreid_src"
if (Test-Path $torchreidSrc) { Remove-Item -Recurse -Force $torchreidSrc }
git clone --depth 1 https://github.com/KaiyangZhou/deep-person-reid.git $torchreidSrc --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host "  WARNING: torchreid clone failed. OSNet Re-ID will be disabled." -ForegroundColor DarkYellow
} else {
    $torchreidDest = ".\venv\Lib\site-packages\torchreid"
    if (Test-Path $torchreidDest) { Remove-Item -Recurse -Force $torchreidDest }
    Copy-Item -Recurse "$torchreidSrc\torchreid" $torchreidDest
    $check = & $VENV_PYTHON -c "import torchreid; from torchreid.utils import FeatureExtractor; print('OK')" 2>&1
    if ($check -match "OK") {
        Write-Host "  OK: torchreid installed and importable." -ForegroundColor Green
    } else {
        Write-Host "  WARNING: torchreid copied but import check failed: $check" -ForegroundColor DarkYellow
    }
}

Write-Host ""
Write-Host "[7/7] Running dependency verification..." -ForegroundColor Yellow
Write-Host ""
& $VENV_PYTHON verify_deps.py
$verifyResult = $LASTEXITCODE

Write-Host ""
if ($verifyResult -eq 0) {
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host " ALL DEPENDENCIES VERIFIED SUCCESSFULLY!" -ForegroundColor Green
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "Start the server with:" -ForegroundColor Cyan
    Write-Host "  .\venv\Scripts\uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" -ForegroundColor White
} else {
    Write-Host "============================================================" -ForegroundColor Red
    Write-Host " SOME DEPENDENCIES FAILED. See output above." -ForegroundColor Red
    Write-Host "============================================================" -ForegroundColor Red
    exit 1
}