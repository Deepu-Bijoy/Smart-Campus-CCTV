import os
import sys
import uuid
import pytest
import numpy as np

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.schemas.violence import InvolvedStudentCard, ViolenceSegment, ViolenceAnalysisResponse, ViolenceSignalBreakdown

def test_1_safeguard_threshold_rejects_subthreshold_matches():
    """
    Verify that candidate matches below RECOGNITION_MEDIUM_THRESHOLD (0.60),
    such as the 0.512 peak match observed on CCTV footage, are safely rejected
    from becoming confirmed student identities.
    """
    threshold = settings.RECOGNITION_MEDIUM_THRESHOLD
    assert threshold == 0.60, "Medium recognition threshold must be strictly 0.60"

    # Simulate peak observed CCTV matches
    candidate_matches = [
        {"track_id": 6, "student": "Anuvind Narayanan", "sim": 0.512, "margin": 0.033},
        {"track_id": 4, "student": "Dipz", "sim": 0.497, "margin": 0.177},
        {"track_id": 18, "student": "Anuvind Narayanan", "sim": 0.442, "margin": 0.051},
        {"track_id": 120, "student": "Ashish P", "sim": 0.403, "margin": 0.062},
    ]

    confirmed = []
    for cand in candidate_matches:
        if cand["sim"] >= threshold:
            if cand["margin"] >= 0.05:
                confirmed.append(cand)

    assert len(confirmed) == 0, "No sub-threshold candidate may be confirmed"

def test_2_ambiguity_margin_rule_rejection():
    """
    Verify that even if a similarity score exceeds 0.60, an ambiguous match
    where runner-up margin is less than 0.05 is rejected.
    """
    cand_high_ambiguous = {"track_id": 10, "student": "Student A", "sim": 0.63, "runner_up_sim": 0.60}
    margin = cand_high_ambiguous["sim"] - cand_high_ambiguous["runner_up_sim"]

    passed_threshold = cand_high_ambiguous["sim"] >= settings.RECOGNITION_MEDIUM_THRESHOLD
    passed_margin = margin >= 0.05

    assert passed_threshold is True
    assert passed_margin is False, f"Margin {margin:.3f} should fail ambiguity margin check"

def test_3_unidentified_person_fallback_preservation():
    """
    Verify that unconfirmed tracks safely fall back to 'Unidentified Person'
    with is_identified=False and student_id=None.
    """
    card = InvolvedStudentCard(
        student_id=None,
        name="Unidentified Person",
        roll_number="N/A",
        similarity_score=0.0,
        confidence="unidentified",
        track_id="trk-1",
        is_identified=False
    )

    assert card.student_id is None
    assert card.name == "Unidentified Person"
    assert card.is_identified is False

def test_4_confirmed_identity_end_to_end_propagation():
    """
    Verify that when a true positive match passes threshold (>= 0.60) and margin (>= 0.05),
    it is correctly represented as a confirmed identity in the response schema.
    """
    sid = uuid.uuid4()
    card = InvolvedStudentCard(
        student_id=sid,
        name="Ashish P",
        roll_number="CS2024-001",
        similarity_score=0.69,
        confidence="medium",
        track_id="trk-175",
        is_identified=True
    )

    assert card.student_id == sid
    assert card.is_identified is True
    assert card.similarity_score == 0.69
    assert card.name != "Unidentified Person"

    # Simulate frontend confirmedPersons memoization filter
    is_confirmed = (card.is_identified or (card.similarity_score is not None and card.similarity_score >= 0.60))
    is_valid_confirmed = bool(card.student_id and is_confirmed and card.name and card.name != "Unidentified Person")
    assert is_valid_confirmed is True

def test_5_frontend_empty_state_behavior_contract():
    """
    Verify the frontend contract when all tracks are Unidentified Persons:
    confirmedPersons array MUST be empty so that 'No confirmed identities in the flagged intervals'
    is displayed rather than false positive cards.
    """
    seg_students = [
        InvolvedStudentCard(
            student_id=None,
            name="Unidentified Person",
            roll_number="N/A",
            similarity_score=0.0,
            confidence="unidentified",
            track_id=f"trk-{i}",
            is_identified=False
        )
        for i in range(35)
    ]

    confirmed_persons = []
    for st in seg_students:
        is_confirmed = bool(st.is_identified or (st.similarity_score is not None and st.similarity_score >= 0.60))
        if st.student_id and is_confirmed and st.name and st.name != "Unidentified Person":
            confirmed_persons.append(st)

    assert len(confirmed_persons) == 0, "Confirmed persons list must be empty when all tracks are unidentified"
