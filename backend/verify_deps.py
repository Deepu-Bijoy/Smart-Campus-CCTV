"""
verify_deps.py
Verifies all AI pipeline dependencies are importable.
Called by setup_env.ps1 after environment creation.
Can also be run manually: python verify_deps.py
"""
import sys

CHECKS = [
    ("torch",             "import torch"),
    ("torchvision",       "import torchvision"),
    ("lap (via lapx)",    "import lap"),
    ("ultralytics/YOLO",  "from ultralytics import YOLO"),
    ("supervision",       "import supervision"),
    ("filterpy",          "import filterpy"),
    ("scipy",             "import scipy"),
    ("cv2 (opencv)",      "import cv2"),
    ("insightface",       "import insightface"),
    ("onnxruntime",       "import onnxruntime"),
    ("transformers/CLIP", "from transformers import CLIPModel"),
    ("qdrant_client",     "import qdrant_client"),
    ("celery",            "import celery"),
    ("fastapi",           "import fastapi"),
    ("sqlalchemy",        "import sqlalchemy"),
    ("torchreid",         "import torchreid"),
]

def get_version(module_name: str) -> str:
    try:
        import importlib
        mod = importlib.import_module(module_name)
        return getattr(mod, "__version__", "installed")
    except Exception:
        return "?"

print()
print("=" * 62)
print("  Pipeline Dependency Verification")
print(f"  Python: {sys.executable}")
print("=" * 62)
print(f"  {'Package':<24} {'Status':<8} {'Version'}")
print("  " + "-" * 56)

passed = []
failed = []

for label, stmt in CHECKS:
    try:
        exec(stmt)
        # Try to get version from first module name in statement
        mod_name = stmt.split("import ")[-1].split(";")[0].strip().split(".")[0]
        ver = get_version(mod_name)
        print(f"  {'[OK]':<6} {label:<24} {ver}")
        passed.append(label)
    except (ImportError, ModuleNotFoundError) as e:
        print(f"  {'[FAIL]':<6} {label:<24} {str(e)[:36]}")
        failed.append((label, str(e)))

print()

# CUDA check
try:
    import torch
    if torch.cuda.is_available():
        gpu = torch.cuda.get_device_name(0)
        mem = torch.cuda.get_device_properties(0).total_memory // (1024 ** 3)
        print(f"  CUDA GPU : {gpu} ({mem} GB) [ENABLED]")
    else:
        print("  CUDA GPU : NOT AVAILABLE — running on CPU only")
        print("             Check CUDA drivers and PyTorch CUDA build.")
except Exception as e:
    print(f"  CUDA GPU : CHECK FAILED — {e}")

# ByteTrack tracker test
try:
    from ultralytics import YOLO
    m = YOLO("yolov8n.pt")
    # Try tracking a blank frame to confirm ByteTrack + lap works
    import numpy as np
    blank = np.zeros((640, 640, 3), dtype=np.uint8)
    result = m.track(blank, tracker="bytetrack.yaml", persist=True, verbose=False)
    print("  ByteTrack: WORKING (bytetrack.yaml + lap assignment confirmed)")
except Exception as e:
    err = str(e)
    if "lap" in err.lower():
        print(f"  ByteTrack: FAILED — lap module error: {err[:60]}")
    else:
        print(f"  ByteTrack: FAILED — {err[:60]}")

print()
print("=" * 62)
print(f"  Results: {len(passed)} passed, {len(failed)} failed")

if failed:
    print()
    print("  MISSING PACKAGES:")
    for name, err in failed:
        print(f"    - {name}: {err[:50]}")
    print()
    print("  Fix: run setup_env.ps1 or install manually inside venv:")
    print("    .\\venv\\Scripts\\pip install <package>")
    print("=" * 62)
    sys.exit(1)
else:
    print()
    print("  ALL DEPENDENCIES PRESENT — Pipeline is ready.")
    print("=" * 62)
    sys.exit(0)
