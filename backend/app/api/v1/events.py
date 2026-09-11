import uuid
import logging
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api import deps
from app.models.user import User
from app.models.event import Event
from app.models.incident import Incident, IncidentPerson, Evidence, DetectedEvent
from app.models.camera import Camera
from app.models.student import Student
from app.schemas.event import EventResponse
from app.event_engine.event_types import EventType
from app.services.investigation_service import IncidentInvestigationQueryEngine

logger = logging.getLogger(__name__)
router = APIRouter()

async def _map_incident_to_event_response(db: AsyncSession, inc: Incident) -> EventResponse:
    cam_stmt = select(Camera).filter(Camera.id == inc.camera_id)
    cam_res = await db.execute(cam_stmt)
    camera = cam_res.scalars().first()
    
    camera_name = camera.name if camera else "Surveillance Camera"
    camera_location = camera.location if camera else "Campus Area"

    ev_stmt = select(DetectedEvent).filter(DetectedEvent.incident_id == inc.id)
    ev_res = await db.execute(ev_stmt)
    det_event = ev_res.scalars().first()
    video_id = det_event.video_id if det_event else None

    # Parse evidence files
    screenshot_url = None
    video_url = None
    for ev in inc.evidences:
        file_url = ev.file_path.replace("\\", "/")
        if "storage/" in file_url:
            file_url = "/" + file_url[file_url.find("storage/"):]
            
        if ev.evidence_type == "video":
            video_url = file_url
        elif ev.evidence_type == "screenshot":
            screenshot_url = file_url

    # Parse student details
    students_list = []
    primary_student_id = None
    primary_student_name = None
    primary_student_roll = None

    if inc.persons:
        for ip in inc.persons:
            student = ip.student
            if not student and ip.student_id:
                std_res = await db.execute(select(Student).filter(Student.id == ip.student_id))
                student = std_res.scalars().first()
                
            if student:
                if not primary_student_id:
                    primary_student_id = student.id
                    primary_student_name = student.name
                    primary_student_roll = student.university_roll_number

                students_list.append({
                    "id": str(student.id),
                    "name": student.name,
                    "roll_number": student.university_roll_number,
                    "class": f"{student.programme} {student.section}",
                    "department": student.department
                })

    event_type_clean = inc.incident_type.upper().replace(" ", "_")
    confidence_label = "high" if inc.confidence >= 0.70 else "medium"

    return EventResponse(
        id=inc.id,
        event_type=event_type_clean,
        camera_id=inc.camera_id,
        camera_name=camera_name,
        camera_location=camera_location,
        video_id=video_id,
        timestamp=inc.timestamp,
        zone_id=None,
        student_id=primary_student_id,
        student_name=primary_student_name,
        student_roll=primary_student_roll,
        students=students_list,
        confidence=confidence_label,
        confidence_score=inc.confidence,
        explanation=inc.explanation,
        evidence_image=screenshot_url,
        evidence_video=video_url,
        tracks=[],
        persons_identified_count=len(students_list)
    )

@router.get("", response_model=List[EventResponse])
@router.get("/", response_model=List[EventResponse])
async def list_events(
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    List all detected surveillance alert events (Fights, Boundary Crossings, Fence Jumps, Restricted Entry, Suspicious Activity).
    """
    results = []

    # 1. Fetch Incidents from DB
    inc_stmt = (
        select(Incident)
        .options(
            selectinload(Incident.persons).selectinload(IncidentPerson.student),
            selectinload(Incident.evidences),
            selectinload(Incident.events)
        )
        .order_by(Incident.timestamp.desc())
    )
    inc_res = await db.execute(inc_stmt)
    incidents = inc_res.scalars().all()

    for inc in incidents:
        results.append(await _map_incident_to_event_response(db, inc))

    # 2. Fetch Events from DB
    evt_stmt = select(Event).options(selectinload(Event.tracks)).order_by(Event.timestamp.desc())
    evt_res = await db.execute(evt_stmt)
    events = evt_res.scalars().all()

    for ev in events:
        cam_res = await db.execute(select(Camera).filter(Camera.id == ev.camera_id))
        camera = cam_res.scalars().first()
        
        std_name = None
        std_roll = None
        if ev.student_id:
            std_res = await db.execute(select(Student).filter(Student.id == ev.student_id))
            student = std_res.scalars().first()
            if student:
                std_name = student.name
                std_roll = student.university_roll_number

        results.append(
            EventResponse(
                id=ev.id,
                event_type=ev.event_type,
                camera_id=ev.camera_id,
                camera_name=camera.name if camera else "Surveillance Camera",
                camera_location=camera.location if camera else "Campus Zone",
                video_id=ev.video_id,
                timestamp=ev.timestamp,
                zone_id=ev.zone_id,
                student_id=ev.student_id,
                student_name=std_name,
                student_roll=std_roll,
                students=[{"id": str(ev.student_id), "name": std_name, "roll_number": std_roll}] if std_name else [],
                confidence=ev.confidence,
                confidence_score=0.95 if ev.confidence == "high" else 0.70,
                explanation=f"Surveillance alert trigger of type {ev.event_type}.",
                tracks=[],
                persons_identified_count=1 if std_name else 0
            )
        )

    # 3. Dynamic Real-Time Incident Search Fallback if no alerts exist in DB
    if not results:
        logger.info("No alert events found in DB. Triggering dynamic real-time incident search fallback...")
        dossiers = await IncidentInvestigationQueryEngine.query_incidents(db, "anomaly fight fence boundary")
        
        # Re-query DB for newly created incidents
        inc_res = await db.execute(inc_stmt)
        incidents = inc_res.scalars().all()
        for inc in incidents:
            results.append(await _map_incident_to_event_response(db, inc))

    # Sort results by timestamp descending
    results.sort(key=lambda x: x.timestamp, reverse=True)
    return results

@router.get("/types", response_model=List[str])
async def list_event_types(
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Get all supported alert category labels.
    """
    return [e.value for e in EventType] + ["VIOLENCE", "FIGHT", "SUSPICIOUS", "RESTRICTED_ENTRY", "BOUNDARY_CROSSING"]

@router.get("/video/{video_id}", response_model=List[EventResponse])
async def list_video_events(
    video_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    List events detected in a specific video feed.
    """
    all_events = await list_events(db, current_user)
    return [e for e in all_events if e.video_id == video_id]

@router.get("/{id}", response_model=EventResponse)
async def get_event(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Retrieve detailed records for an event by ID.
    """
    # 1. Search Incident table
    inc_stmt = (
        select(Incident)
        .options(
            selectinload(Incident.persons).selectinload(IncidentPerson.student),
            selectinload(Incident.evidences),
            selectinload(Incident.events)
        )
        .filter(Incident.id == id)
    )
    inc_res = await db.execute(inc_stmt)
    inc = inc_res.scalars().first()
    if inc:
        return await _map_incident_to_event_response(db, inc)

    # 2. Search Event table
    evt_stmt = (
        select(Event)
        .options(selectinload(Event.tracks))
        .filter(Event.id == id)
    )
    evt_res = await db.execute(evt_stmt)
    event_obj = evt_res.scalars().first()
    if event_obj:
        cam_res = await db.execute(select(Camera).filter(Camera.id == event_obj.camera_id))
        camera = cam_res.scalars().first()
        
        std_name = None
        std_roll = None
        if event_obj.student_id:
            std_res = await db.execute(select(Student).filter(Student.id == event_obj.student_id))
            student = std_res.scalars().first()
            if student:
                std_name = student.name
                std_roll = student.university_roll_number

        return EventResponse(
            id=event_obj.id,
            event_type=event_obj.event_type,
            camera_id=event_obj.camera_id,
            camera_name=camera.name if camera else "Surveillance Camera",
            camera_location=camera.location if camera else "Campus Zone",
            video_id=event_obj.video_id,
            timestamp=event_obj.timestamp,
            zone_id=event_obj.zone_id,
            student_id=event_obj.student_id,
            student_name=std_name,
            student_roll=std_roll,
            students=[{"id": str(event_obj.student_id), "name": std_name, "roll_number": std_roll}] if std_name else [],
            confidence=event_obj.confidence,
            confidence_score=0.95 if event_obj.confidence == "high" else 0.70,
            explanation=f"Surveillance alert trigger of type {event_obj.event_type}.",
            tracks=[],
            persons_identified_count=1 if std_name else 0
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Event not found."
    )
