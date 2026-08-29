# F20: AI Investigation Report Generator

## Purpose
The **AI Investigation Report Generator** compiles security, tracking, and explainable scoring evidence logs into formatted, printable investigation reports.

---

## 1. Database Schema
Stores report details:
- `reports`
  * `id` (UUID, PK)
  * `title` (String)
  * `incident_type` (String)
  * `student_id` (UUID, FK to `students.id`, nullable=True)
  * `created_at` (DateTime, timezone=True)
  * `data` (JSON) - holds the compiled timeline lists, student metadata, scores, and narrative.

---

## 2. Supported Export Formats
Reports are downloadable via parameter formatting:
- `format=json`: Returns raw JSON file.
- `format=html` / `format=pdf`: Returns CSS-styled HTML document layout ready for PDF printing.

---

## 3. Exposed REST APIs
- `POST /api/v1/reports/generate`: Generates and stores a new report payload.
- `GET /api/v1/reports/{id}`: Detailed view of a report.
- `GET /api/v1/reports/download/{id}?format={json|html|pdf}`: Downloads formatted reports.
