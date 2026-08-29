# F14: Investigation Backend API

## Purpose
The **Investigation Backend API** provides endpoints for the dashboard metrics, tracking histories timeline builder, incident evidence aggregating, and video asset-specific tracks/detections queries.

---

## 1. Exposed REST APIs

### 1. Dashboard Aggregations
- **Endpoint**: `/api/v1/dashboard`
- **Method**: `GET`
- **Response**: `DashboardResponse`
- **Description**: Returns the count of videos, tracks, detections, enrolled students, face embeddings, and system processing health.

### 2. Multi-Target Timeline Builder
- **Endpoint**: `/api/v1/timeline/{target_id}`
- **Method**: `GET`
- **Response**: `TimelineResponse`
- **Description**: Dynamically resolves the `target_id` path parameter to either:
  * **Student Profile**: Returns a chronological timeline of enrollment and vector similarity match events.
  * **Track Trajectory**: Returns a chronological timeline of coordinate detections.
- **Direct Student Alias**: `/api/v1/students/{id}/timeline`

### 3. Incident Evidence Aggregator
- **Endpoint**: `/api/v1/evidence/{incident_id}`
- **Method**: `GET`
- **Response**: `EvidenceResponse`
- **Description**: Aggregates severity tags, media crop paths, and related track IDs.

### 4. Video-Specific Track & Detection Details
- **Endpoint**: `/api/v1/videos/{id}/tracks`
- **Method**: `GET`
- **Response**: `List[TrackResponse]`
  * Lists all trajectories registered for a video.
- **Endpoint**: `/api/v1/videos/{id}/detections`
- **Method**: `GET`
- **Response**: `List[DetectionResponse]`
  * Lists all individual coordinate detections registered for a video.

---

## 2. Dynamic Resolution Architecture
```mermaid
graph TD
    User([Security Operator]) -->|GET /timeline/{target_id}| Router[APIRouter]
    Router -->|Query Student| DB[(PostgreSQL)]
    DB -->|Found| StudentTimeline[Compile Enrollment & Match Events]
    DB -->|Not Found| QueryTrack[Query Track]
    QueryTrack -->|Found| TrackTimeline[Compile Detection Coordinates]
    QueryTrack -->|Not Found| Fail[404 Target Not Found]
```
