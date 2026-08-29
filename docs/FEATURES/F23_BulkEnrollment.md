# F23: Bulk Student Import & Bulk Face Enrollment

## Feature Description
Enables college administrators to import hundreds or thousands of students automatically using CSV/Excel lists and bulk upload directories of face photos matching student Roll Numbers.

## Architecture & Data Flow
1. **Spreadsheet Parse**: CSV or Excel file is parsed in FastAPI via Pandas, validating fields and saving active student accounts to PostgreSQL.
2. **ZIP Dataset Extraction**: Zip file structured by Student Roll Numbers is uploaded, unpacked to a temporary directory, and matches folder names to student Roll Numbers.
3. **Asynchronous Celery Processing**: Face embedding processes run on the `gpu_queue` to protect VRAM space, extracting poses, crops, and ArcFace features.
4. **Diagnostic Reports**: Detailed error sheets tracking missing views, duplicate embeddings, or failed face checks are generated in JSON and CSV.

## API Endpoints
- `POST /api/v1/students/import`: Spreadsheet parsing.
- `POST /api/v1/students/import/photos`: Zip dataset photo matching.
- `POST /api/v1/students/import/enroll`: Triggers Celery enrollment tasks.
- `GET /api/v1/students/import/status/{job_id}`: Progress stats.
- `GET /api/v1/students/import/report/{job_id}`: JSON/CSV diagnostic download.
