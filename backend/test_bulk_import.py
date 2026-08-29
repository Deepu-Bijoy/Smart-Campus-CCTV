import sys
import os
import uuid
import io
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

# Mock out heavy deep learning models and clients
sys.modules['ultralytics'] = MagicMock()
sys.modules['torchreid'] = MagicMock()
sys.modules['torchreid.utils'] = MagicMock()
sys.modules['qdrant_client'] = MagicMock()
sys.modules['qdrant_client.http'] = MagicMock()
sys.modules['transformers'] = MagicMock()
sys.modules['insightface'] = MagicMock()
sys.modules['insightface.app'] = MagicMock()

backend_path = r"c:\Users\Asus\OneDrive\Desktop\AI-Powered Smart CCTV Investigation System\backend"
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from fastapi.testclient import TestClient
from fastapi import status
from app.main import app
from app.api import deps
from app.models.user import User
from app.models.bulk_import import BulkImportJob

mock_user = User(
    id=uuid.UUID("d3b7a123-4567-89ab-cdef-0123456789ab"),
    email="operator@smartcampus.com",
    hashed_password="hashedpassword123",
    full_name="Lead Security Operator",
    is_active=True
)

app.dependency_overrides[deps.get_current_user] = lambda: mock_user

client = TestClient(app)

class MockScalarResult:
    def __init__(self, value):
        self._value = value
    def first(self):
        if isinstance(self._value, list):
            return self._value[0] if self._value else None
        return self._value
    def all(self):
        return [self._value] if not isinstance(self._value, list) else self._value

class MockSQLResult:
    def __init__(self, value):
        self._value = value
    def scalars(self):
        return MockScalarResult(self._value)

def test_bulk_spreadsheet_import():
    csv_content = (
        "roll_number,name,department,programme,year,semester,section,email\n"
        "CSE22001,John Doe,CSE,B.Tech,3,6,A,john.doe@university.edu\n"
        "CSE22002,Jane Smith,CSE,B.Tech,3,6,A,jane.smith@university.edu\n"
    )
    
    file = ("students.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")

    mock_job = BulkImportJob(
        id=uuid.uuid4(),
        status="completed",
        total_records=2,
        processed_records=2,
        successful_records=2,
        failed_records=0,
        report={"summary": "Spreadsheet import completed.", "errors": [], "success_items": []},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )

    async def mock_execute(stmt):
        stmt_str = str(stmt).lower()
        if "bulk_import_jobs" in stmt_str or "bulkimportjob" in stmt_str:
            return MockSQLResult(mock_job)
        return MockSQLResult(None)

    async def mock_commit():
        pass

    async def mock_refresh(obj):
        pass

    mock_db = MagicMock()
    mock_db.execute = mock_execute
    mock_db.add = lambda x: None
    mock_db.commit = mock_commit
    mock_db.refresh = mock_refresh
    
    app.dependency_overrides[deps.get_db] = lambda: mock_db

    print("Checking POST /students/import...")
    response = client.post(
        "/api/v1/students/import",
        files={"file": file}
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["total_records"] == 2
    assert data["status"] == "completed"

    print("Checking GET /students/import/status/{job_id}...")
    response = client.get(f"/api/v1/students/import/status/{mock_job.id}")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["total_records"] == 2

    print("Checking PUT /students/import/cancel/{job_id}...")
    response = client.put(f"/api/v1/students/import/cancel/{mock_job.id}")
    assert response.status_code == status.HTTP_200_OK

    print("Checking GET /students/import/report/{job_id}...")
    response = client.get(f"/api/v1/students/import/report/{mock_job.id}")
    assert response.status_code == status.HTTP_200_OK

    print("All bulk spreadsheet import tests verified successfully!")

if __name__ == "__main__":
    test_bulk_spreadsheet_import()
