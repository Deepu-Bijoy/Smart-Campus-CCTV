# F13: Student Face Enrollment & Face Embedding Engine

## Purpose
The **Student Face Enrollment & Face Embedding Engine** converts registered student photographs into 512-dimensional searchable face embeddings. It applies quality gates to ensure high accuracy for future CCTV matching.

## Scope
This module handles **enrollment only**. It does not perform CCTV identification yet.

## Architecture
```mermaid
graph TD
    StudentPhotos[Student Photo Files] -->|POST /students/{id}/enroll| Router[API Router]
    Router -->|Load Image| CV[OpenCV Read]
    CV -->|Face Detection| Engine[FaceEnrollmentEngine]
    Engine -->|InsightFace Buffalo_L| Gate{Quality Gates}
    Gate -->|Pass| PG[(PostgreSQL db)]
    Gate -->|Pass| Qdrant[(Qdrant Vector DB)]
    Gate -->|Fail| Return[Error Log JSON]
```

## Validation & Quality Gates
Before generating embeddings, every image must pass through these constraints:
1. **Face Count Check**: Exactly 1 face must be detected. Rejects images with 0 or multiple faces.
2. **Dimension Check**: The bounding box height and width must be $\ge 80$ pixels.
3. **Quality Gate (det_score)**: InsightFace detection confidence must be $\ge 0.60$.
4. **Blur Gate**: Evaluated using the Laplacian variance of the face crop:
   $$\text{blur\_score} = \text{Variance}(\text{Laplacian}(\text{GrayCrop}))$$
   Images with $\text{blur\_score} < 50.0$ are rejected.
5. **Duplicate Embedding Gate**: Queries Qdrant to find closest vectors; if similarity $> 0.95$ matches another student, it is rejected.

---

## Database Tables

### `student_face_embeddings`
Stores details of generated embeddings:
- `id` (UUID, PK)
- `student_id` (UUID, FK to `students.id`)
- `photo_id` (UUID, FK to `student_photos.id`)
- `embedding` (ARRAY of Float, size 512)
- `model_version` (String, default: `"buffalo_l"`)
- `quality_score` (Float)
- `blur_score` (Float)
- `pose_yaw`, `pose_pitch`, `pose_roll` (Float)
- `face_bbox` (JSON)

---

## Qdrant Configuration

### Collection: `student_face_embeddings`
- **Vector Dimension**: `512`
- **Distance Metric**: `Cosine`
- **Payload Schema**:
  * `student_id` (UUID as string)
  * `photo_id` (UUID as string)
  * `view` (String, angle)
  * `quality` (Float)
  * `department` (String)
  * `year` (Integer)

---

## Enrollment Endpoints

### 1. Trigger Face Enrollment
- **Endpoint**: `/api/v1/students/{id}/enroll`
- **Method**: `POST`
- **Purpose**: Triggers embedding extraction on all uploaded student photos.
- **Response**: `EnrollmentSummaryResponse` detailing processed, successful, failed count, quality scores per angle, and detailed error logs for failures.

### 2. Retrieve Enrollment Status
- **Endpoint**: `/api/v1/students/{id}/enrollment-status`
- **Method**: `GET`
- **Purpose**: Returns the count of embeddings, missing views, and individual quality scores.
