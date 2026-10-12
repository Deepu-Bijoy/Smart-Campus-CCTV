import os
import sys
import uuid
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.api.v1.violence import _compile_violence_dossier
from app.models.video import Video
from app.models.incident import Incident, IncidentPerson, Evidence, DetectedEvent
from app.models.track import Track, Detection
from app.models.student import Student
from app.models.recognition import StudentRecognitionEvent
from app.schemas.violence import ViolenceAnalysisResponse

@pytest.fixture
def mock_db_data():
    """Sets up an in-memory mock scenario with 1 confirmed track and 1 unidentified track."""
    video_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    student_id = uuid.uuid4()
    confirmed_track_id = uuid.uuid4()
    unidentified_track_id = uuid.uuid4()

    video = Video(
        id=video_id,
        title="Test CCTV Footage",
        filename="test_cctv.mp4",
        file_path="storage/test_cctv.mp4",
        duration=60.0,
        status="completed"
    )

    incident = Incident(
        id=incident_id,
        incident_type="Violence",
        confidence=0.88,
        timestamp=datetime.now(timezone.utc),
        explanation="X3D-M video temporal model detected physical altercation from 10.0s to 15.0s (duration 5.0s, confidence 88.0%)."
    )

    student = Student(
        id=student_id,
        name="Ashish P",
        university_roll_number="CS2024-001",
        programme="BTech",
        section="A"
    )

    inc_person = IncidentPerson(
        id=uuid.uuid4(),
        incident_id=incident_id,
        student_id=student_id,
        confidence=0.72
    )
    inc_person.student = student
    incident.persons = [inc_person]

    det_event = DetectedEvent(
        id=uuid.uuid4(),
        video_id=video_id,
        incident_id=incident_id,
        event_type="VIOLENCE",
        confidence=0.88,
        timestamp=datetime.now(timezone.utc)
    )
    incident.events = [det_event]

    evidence_frame = Evidence(
        id=uuid.uuid4(),
        incident_id=incident_id,
        evidence_type="screenshot",
        file_path="storage/evidence/test_frame.jpg"
    )
    evidence_video = Evidence(
        id=uuid.uuid4(),
        incident_id=incident_id,
        evidence_type="video",
        file_path="storage/evidence/test_clip.mp4"
    )
    incident.evidences = [evidence_frame, evidence_video]

    det_1 = Detection(
        id=uuid.uuid4(),
        track_id=confirmed_track_id,
        frame_number=300,
        timestamp_seconds=10.5,
        bounding_box=[100.0, 150.0, 200.0, 350.0],
        confidence=0.92
    )
    track_confirmed = Track(
        id=confirmed_track_id,
        video_id=video_id,
        object_class="person",
        tracker_id=1,
        start_time=9.0,
        end_time=16.0,
        identified_student_id=student_id,
        key_frame_path="storage/crops/crop_trk_1_face_f300.jpg",
        detections=[det_1]
    )

    det_2 = Detection(
        id=uuid.uuid4(),
        track_id=unidentified_track_id,
        frame_number=320,
        timestamp_seconds=11.2,
        bounding_box=[250.0, 160.0, 340.0, 360.0],
        confidence=0.89
    )
    track_unidentified = Track(
        id=unidentified_track_id,
        video_id=video_id,
        object_class="person",
        tracker_id=2,
        start_time=10.0,
        end_time=15.0,
        identified_student_id=None,
        key_frame_path="storage/crops/crop_trk_2_body_f320.jpg",
        detections=[det_2]
    )

    rec_event = StudentRecognitionEvent(
        id=uuid.uuid4(),
        track_id=confirmed_track_id,
        student_id=student_id,
        video_id=video_id,
        similarity_score=0.72,
        confidence="medium"
    )

    return {
        "video": video,
        "incident": incident,
        "student": student,
        "track_confirmed": track_confirmed,
        "track_unidentified": track_unidentified,
        "rec_event": rec_event,
        "all_tracks": [track_confirmed, track_unidentified]
    }

def _build_mock_db_session(data):
    """Creates a mock AsyncSession that returns predefined objects without touching the real DB."""
    db = AsyncSession_mock = AsyncMock()

    async def mock_execute(stmt):
        stmt_str = str(stmt).lower()
        res = MagicMock()

        if "from incidents" in stmt_str or "incident" in stmt_str:
            scalars_mock = MagicMock()
            scalars_mock.unique.return_value.all.return_value = [data["incident"]]
            scalars_mock.first.return_value = data["incident"]
            res.scalars.return_value = scalars_mock
        elif "from tracks" in stmt_str:
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = data["all_tracks"]
            res.scalars.return_value = scalars_mock
        elif "from students" in stmt_str:
            scalars_mock = MagicMock()
            scalars_mock.first.return_value = data["student"]
            scalars_mock.all.return_value = [data["student"]]
            res.scalars.return_value = scalars_mock
        elif "student_recognition_events" in stmt_str:
            scalars_mock = MagicMock()
            params = {}
            try:
                params = stmt.compile().params
            except Exception:
                pass
            if data["track_unidentified"].id in params.values() or str(data["track_unidentified"].id) in stmt_str:
                scalars_mock.first.return_value = None
                scalars_mock.all.return_value = []
            else:
                scalars_mock.first.return_value = data["rec_event"]
                scalars_mock.all.return_value = [data["rec_event"]]
            res.scalars.return_value = scalars_mock
        elif "from incident_persons" in stmt_str:
            scalars_mock = MagicMock()
            scalars_mock.first.return_value = data["incident"].persons[0]
            res.scalars.return_value = scalars_mock
        elif "from person_reids" in stmt_str:
            scalars_mock = MagicMock()
            scalars_mock.first.return_value = None
            res.scalars.return_value = scalars_mock
        else:
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = []
            scalars_mock.first.return_value = None
            res.scalars.return_value = scalars_mock
        return res

    db.execute.side_effect = mock_execute
    return db

@pytest.mark.anyio
async def test_dossier_compilation_never_invokes_face_engine_or_identifier(mock_db_data):
    """
    Test 1: Verify that _compile_violence_dossier does NOT instantiate
    or call FaceEnrollmentEngine or StudentIdentifier.
    """
    db = _build_mock_db_session(mock_db_data)

    with patch("app.pipeline.face_engine.FaceEnrollmentEngine.process_photo") as mock_process, \
         patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop") as mock_identify:

        dossier = await _compile_violence_dossier(db, mock_db_data["video"], None)

        assert isinstance(dossier, ViolenceAnalysisResponse)
        mock_process.assert_not_called()
        mock_identify.assert_not_called()

@pytest.mark.anyio
async def test_persisted_confirmed_identity_preserved_in_dossier(mock_db_data):
    """
    Test 2: Verify that a previously confirmed student identity in DB
    is preserved with full fields and correct similarity score.
    """
    db = _build_mock_db_session(mock_db_data)

    dossier = await _compile_violence_dossier(db, mock_db_data["video"], None)

    assert len(dossier.identified_students) >= 1
    found = next((s for s in dossier.identified_students if s.student_id == mock_db_data["student"].id), None)
    assert found is not None
    assert found.name == "Ashish P"
    assert found.roll_number == "CS2024-001"
    assert found.is_identified is True
    assert found.similarity_score == 0.72

@pytest.mark.anyio
async def test_unidentified_track_remains_unidentified(mock_db_data):
    """
    Test 3: Verify that tracks without a confirmed identity are correctly
    marked as Unidentified Person without triggering face search.
    """
    db = _build_mock_db_session(mock_db_data)

    dossier = await _compile_violence_dossier(db, mock_db_data["video"], None)

    assert len(dossier.segments) == 1
    seg = dossier.segments[0]
    trk_cards = seg.tracks

    unidentified_trk = next((t for t in trk_cards if t.tracker_id == 2), None)
    assert unidentified_trk is not None
    assert unidentified_trk.identified_student is not None
    assert unidentified_trk.identified_student.name == "Unidentified Person"
    assert unidentified_trk.identified_student.is_identified is False
    assert unidentified_trk.identified_student.student_id is None

@pytest.mark.anyio
async def test_existing_evidence_and_response_fields_intact(mock_db_data):
    """
    Test 4: Verify that all evidence URLs, breakdown scores, and timestamps
    remain strictly intact in the response schema.
    """
    db = _build_mock_db_session(mock_db_data)

    dossier = await _compile_violence_dossier(db, mock_db_data["video"], None)

    assert dossier.status == "VIOLENCE_DETECTED"
    assert len(dossier.segments) == 1
    seg = dossier.segments[0]
    assert seg.start_time == 10.0
    assert seg.end_time == 15.0
    assert seg.duration == 5.0
    assert seg.timestamp_display == "00:00:10 - 00:00:15"
    assert seg.confidence == 0.88
    assert seg.breakdown.motion_dynamics > 0.0
    assert len(seg.tracks) == 2

@pytest.mark.anyio
async def test_repeated_result_requests_zero_biometric_inference(mock_db_data):
    """
    Test 5: Verify that repeated calls to _compile_violence_dossier
    (simulating multiple GET /result requests) perform 0 biometric inferences.
    """
    db = _build_mock_db_session(mock_db_data)

    with patch("app.pipeline.face_engine.FaceEnrollmentEngine.process_photo") as mock_process, \
         patch("app.services.student_identifier.StudentIdentifier.identify_face_in_crop") as mock_identify:

        for _ in range(5):
            d = await _compile_violence_dossier(db, mock_db_data["video"], None)
            assert d.status == "VIOLENCE_DETECTED"

        assert mock_process.call_count == 0
        assert mock_identify.call_count == 0
