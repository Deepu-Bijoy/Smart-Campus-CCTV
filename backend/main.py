"""
Main application entry point for the backend.
Exposes the FastAPI 'app' instance from app.main to support running:
    uvicorn main:app --reload
from the backend/ directory, as well as direct execution:
    python main.py
"""
import sys
from pathlib import Path

# Ensure backend root directory is in sys.path so 'app' and subpackages resolve
backend_dir = Path(__file__).resolve().parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
