import uuid
import logging
import re
from typing import Any, List, Optional, Tuple, Dict
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, or_, cast, String, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api import deps
from app.models.user import User
from app.models.event import Event, EventTrack
from app.models.incident import Incident, IncidentPerson, Evidence, DetectedEvent
from app.models.camera import Camera
from app.models.student import Student
from app.models.video import Video
from app.models.report import Report
from app.schemas.event import EventResponse
from app.event_engine.event_types import EventType
from app.services.investigation_service import IncidentInvestigationQueryEngine

logger = logging.getLogger(__name__)
router = APIRouter()

def _format_video_timestamp(seconds: Optional[float], preserve_millis: bool = True) -> Optional[str]:
    if seconds is None or seconds < 0:
        return None
    total_ms = int(round(seconds * 1000))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    if preserve_millis and ms > 0:
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"
    return f"{h:02d}:{m:02d}:{s:02d}"

def _extract_video_timing(
    explanation: Optional[str],
    evidences: list,
    video_obj: Optional[Video] = None
) -> tuple[Optional[str], Optional[str], Optional[float], Optional[float], Optional[float]]:
    expl = explanation or ""
    
    # 1. Temporal altercation window: 'from X.Xs to Y.Ys'
    range_match = re.search(r'from\s+(\d+(?:\.\d+)?)\s*s\s+to\s+(\d+(?:\.\d+)?)\s*s', expl, re.IGNORECASE)
    if range_match:
        start_sec = float(range_match.group(1))
        end_sec = float(range_match.group(2))
        # Authoritative screenshot keyframe captured at temporal midpoint:
        mid_sec = (start_sec + end_sec) / 2.0
        det_str = _format_video_timestamp(mid_sec, preserve_millis=True)
        int_str = f"{_format_video_timestamp(start_sec, preserve_millis=False)} - {_format_video_timestamp(end_sec, preserve_millis=False)}"
        return det_str, int_str, mid_sec, start_sec, end_sec

    # 2. Point detection: 'at X.Xs'
    at_match = re.search(r'at\s+(\d+(?:\.\d+)?)\s*s', expl, re.IGNORECASE)
    if at_match:
        sec = float(at_match.group(1))
        det_str = _format_video_timestamp(sec, preserve_millis=True)
        return det_str, None, sec, sec, sec

    # 3. Explicit time in explanation: HH:MM:SS
    time_match = re.search(r'(\d{2}:\d{2}:\d{2}(?:\.\d+)?)', expl)
    if time_match:
        ts_val = time_match.group(1)
        parts = ts_val.split(':')
        if len(parts) == 3:
            try:
                s_val = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                return ts_val, None, s_val, s_val, s_val
            except Exception:
                pass

    # 4. Evidence crop filename pattern: <track>_<frame>_<hash>.jpg
    fps = (video_obj.fps if video_obj and video_obj.fps and video_obj.fps > 0 else 30.0)
    for ev in evidences:
        fp = getattr(ev, "file_path", "") or ""
        crop_match = re.search(r'_(\d+)_([a-f0-9]+)\.jpg$', fp, re.IGNORECASE)
        if crop_match:
            frame_num = int(crop_match.group(1))
            sec = frame_num / fps
            det_str = _format_video_timestamp(sec, preserve_millis=True)
            return det_str, None, sec, sec, sec

    # 5. Segment evidence naming: _seg(\d+)
    for ev in evidences:
        fp = getattr(ev, "file_path", "") or ""
        seg_match = re.search(r'_seg(\d+)\.', fp, re.IGNORECASE)
        if seg_match:
            seg_idx = int(seg_match.group(1))
            approx_sec = seg_idx * 6.0
            det_str = _format_video_timestamp(approx_sec, preserve_millis=False)
            return det_str, None, approx_sec, approx_sec, approx_sec

    # Never substitute DB insertion / wall-clock time
    return None, None, None, None, None

def _build_student_academic_detail(student: Student) -> dict:
    photo_url = None
    if student.photos:
        front_photo = next((p for p in student.photos if (p.view or "").lower() == "front"), None) or student.photos[0]
        p_path = (front_photo.photo_path or "").replace("\\", "/")
        if "storage/" in p_path:
            photo_url = "/" + p_path[p_path.find("storage/"):]
        elif p_path:
            photo_url = f"/{p_path.lstrip('/')}"

    cls_name = student.programme or "Not available"
    dept_name = student.department or "Not available"
    sec_name = student.section or "Not available"
    sem_val = student.semester if student.semester is not None else None
    yr_val = student.year if student.year is not None else None

    return {
        "id": str(student.id),
        "student_id": str(student.id),
        "name": student.name,
        "roll_number": student.university_roll_number or "Not available",
        "class": cls_name,
        "class_name": cls_name,
        "programme": cls_name,
        "department": dept_name,
        "semester": sem_val,
        "year": yr_val,
        "section": sec_name,
        "photo_url": photo_url,
        "profile_photo_url": photo_url
    }

async def _map_incident_to_event_response(db: AsyncSession, inc: Incident) -> EventResponse:
    camera = getattr(inc, "camera", None)
    if not camera and inc.camera_id:
        cam_stmt = select(Camera).filter(Camera.id == inc.camera_id)
        cam_res = await db.execute(cam_stmt)
        camera = cam_res.scalars().first()
    
    camera_name = camera.name if camera else "Surveillance Camera"
    camera_location = camera.location if camera else "Campus Area"

    det_event = inc.events[0] if (getattr(inc, "events", None) and len(inc.events) > 0) else None
    if not det_event:
        ev_stmt = select(DetectedEvent).options(selectinload(DetectedEvent.video)).filter(DetectedEvent.incident_id == inc.id)
        ev_res = await db.execute(ev_stmt)
        det_event = ev_res.scalars().first()
    video_id = det_event.video_id if det_event else None

    # Parse evidence files
    screenshot_url = None
    video_url = None
    for ev in (inc.evidences or []):
        file_url = ev.file_path.replace("\\", "/")
        if "storage/" in file_url:
            file_url = "/" + file_url[file_url.find("storage/"):]
            
        if ev.evidence_type == "video":
            video_url = file_url
        elif ev.evidence_type == "screenshot":
            screenshot_url = file_url

    # Resolve video information
    video_name = None
    video_obj = getattr(det_event, "video", None) if det_event else None
    if not video_obj and video_id:
        vid_hex = video_id.hex if hasattr(video_id, "hex") else str(video_id)
        vid_stmt = select(Video).filter(
            or_(
                Video.id == video_id,
                cast(Video.id, String) == vid_hex,
                cast(Video.id, String) == str(video_id)
            )
        )
        vid_res = await db.execute(vid_stmt)
        video_obj = vid_res.scalars().first()
    if video_obj:
        video_name = video_obj.original_filename or video_obj.title

    # Resolve authoritative video-relative timing
    video_ts, video_interval, det_sec, start_sec, end_sec = _extract_video_timing(
        inc.explanation,
        inc.evidences or [],
        video_obj
    )

    # Parse student details with full academic records and photos
    students_list = []
    primary_student_id = None
    primary_student_name = None
    primary_student_roll = None

    if inc.persons:
        for ip in inc.persons:
            student = getattr(ip, "student", None)
            if not student and ip.student_id:
                std_res = await db.execute(
                    select(Student).options(selectinload(Student.photos)).filter(Student.id == ip.student_id)
                )
                student = std_res.scalars().first()
                
            if student:
                if not primary_student_id:
                    primary_student_id = student.id
                    primary_student_name = student.name
                    primary_student_roll = student.university_roll_number

                students_list.append(_build_student_academic_detail(student))

    event_type_clean = inc.incident_type.upper().replace(" ", "_")
    confidence_label = "high" if inc.confidence >= 0.70 else "medium"

    return EventResponse(
        id=inc.id,
        event_type=event_type_clean,
        camera_id=inc.camera_id,
        camera_name=camera_name,
        camera_location=camera_location,
        video_id=video_id,
        video_name=video_name,
        video_timestamp=video_ts,
        video_timestamp_interval=video_interval,
        video_timestamp_seconds=det_sec,
        video_start_seconds=start_sec,
        video_end_seconds=end_sec,
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

    # 1. Fetch Incidents from DB with eager loaded camera, persons, student photos, evidences, and events->video
    inc_stmt = (
        select(Incident)
        .options(
            selectinload(Incident.camera),
            selectinload(Incident.persons).selectinload(IncidentPerson.student).selectinload(Student.photos),
            selectinload(Incident.evidences),
            selectinload(Incident.events).selectinload(DetectedEvent.video)
        )
        .order_by(Incident.timestamp.desc())
    )
    inc_res = await db.execute(inc_stmt)
    incidents = inc_res.scalars().all()

    for inc in incidents:
        results.append(await _map_incident_to_event_response(db, inc))

    # 2. Fetch Events from DB with batch map lookups for cameras and students
    evt_stmt = select(Event).options(selectinload(Event.tracks)).order_by(Event.timestamp.desc())
    evt_res = await db.execute(evt_stmt)
    events = evt_res.scalars().all()

    if events:
        cam_ids = {ev.camera_id for ev in events if ev.camera_id}
        std_ids = {ev.student_id for ev in events if ev.student_id}

        cams_map = {}
        if cam_ids:
            cams_res = await db.execute(select(Camera).filter(Camera.id.in_(cam_ids)))
            cams_map = {c.id: c for c in cams_res.scalars().all()}

        stds_map = {}
        if std_ids:
            stds_res = await db.execute(
                select(Student).options(selectinload(Student.photos)).filter(Student.id.in_(std_ids))
            )
            stds_map = {s.id: s for s in stds_res.scalars().all()}

        for ev in events:
            camera = cams_map.get(ev.camera_id)
            student = stds_map.get(ev.student_id) if ev.student_id else None

            std_name = student.name if student else None
            std_roll = student.university_roll_number if student else None
            st_items = [_build_student_academic_detail(student)] if student else []

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
                    students=st_items,
                    confidence=ev.confidence,
                    confidence_score=0.95 if ev.confidence == "high" else 0.70,
                    explanation=f"Surveillance alert trigger of type {ev.event_type}.",
                    tracks=[],
                    persons_identified_count=len(st_items)
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
    id_hex = id.hex if hasattr(id, "hex") else str(id)
    # 1. Search Incident table
    inc_stmt = (
        select(Incident)
        .options(
            selectinload(Incident.camera),
            selectinload(Incident.persons).selectinload(IncidentPerson.student).selectinload(Student.photos),
            selectinload(Incident.evidences),
            selectinload(Incident.events).selectinload(DetectedEvent.video)
        )
        .filter(
            or_(
                Incident.id == id,
                cast(Incident.id, String) == id_hex,
                cast(Incident.id, String) == str(id)
            )
        )
    )
    inc_res = await db.execute(inc_stmt)
    inc = inc_res.scalars().first()
    if inc:
        return await _map_incident_to_event_response(db, inc)

    # 2. Search Event table
    evt_stmt = (
        select(Event)
        .options(selectinload(Event.tracks))
        .filter(
            or_(
                Event.id == id,
                cast(Event.id, String) == id_hex,
                cast(Event.id, String) == str(id)
            )
        )
    )
    evt_res = await db.execute(evt_stmt)
    event_obj = evt_res.scalars().first()
    if event_obj:
        cam_res = await db.execute(select(Camera).filter(Camera.id == event_obj.camera_id))
        camera = cam_res.scalars().first()
        
        std_name = None
        std_roll = None
        st_items = []
        if event_obj.student_id:
            std_res = await db.execute(
                select(Student).options(selectinload(Student.photos)).filter(Student.id == event_obj.student_id)
            )
            student = std_res.scalars().first()
            if student:
                std_name = student.name
                std_roll = student.university_roll_number
                st_items.append(_build_student_academic_detail(student))

        vid_name = None
        vid_ts = None
        vid_sec = None
        if event_obj.video_id:
            v_res = await db.execute(
                select(Video).filter(
                    or_(
                        Video.id == event_obj.video_id,
                        cast(Video.id, String) == (event_obj.video_id.hex if hasattr(event_obj.video_id, "hex") else str(event_obj.video_id)),
                        cast(Video.id, String) == str(event_obj.video_id)
                    )
                )
            )
            v_row = v_res.scalars().first()
            if v_row:
                vid_name = v_row.original_filename or v_row.title

        # Determine video timing from tracks
        if event_obj.tracks:
            for trk in event_obj.tracks:
                if hasattr(trk, "start_time") and trk.start_time is not None:
                    vid_sec = trk.start_time
                    vid_ts = _format_video_timestamp(vid_sec)
                    break

        return EventResponse(
            id=event_obj.id,
            event_type=event_obj.event_type,
            camera_id=event_obj.camera_id,
            camera_name=camera.name if camera else "Surveillance Camera",
            camera_location=camera.location if camera else "Campus Zone",
            video_id=event_obj.video_id,
            video_name=vid_name,
            video_timestamp=vid_ts,
            video_timestamp_seconds=vid_sec,
            timestamp=event_obj.timestamp,
            zone_id=event_obj.zone_id,
            student_id=event_obj.student_id,
            student_name=std_name,
            student_roll=std_roll,
            students=st_items,
            confidence=event_obj.confidence,
            confidence_score=0.95 if event_obj.confidence == "high" else 0.70,
            explanation=f"Surveillance alert trigger of type {event_obj.event_type}.",
            tracks=[],
            persons_identified_count=len(st_items)
        )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Event not found."
    )

@router.delete("/{id}")
async def delete_event(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Delete a security alert event by ID.
    Enforces authorization: requires admin role.
    Atomically deletes the alert and exclusively owned dependent records while
    preserving shared videos, students, and reports.
    """
    if (current_user.role or "").lower() != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required to delete security alerts."
        )

    target_hex = id.hex if hasattr(id, "hex") else str(id)

    # 1. Search Incident table
    inc_stmt = select(Incident).filter(
        or_(
            Incident.id == id,
            cast(Incident.id, String) == target_hex,
            cast(Incident.id, String) == str(id)
        )
    )
    inc_res = await db.execute(inc_stmt)
    inc = inc_res.scalars().first()

    if inc:
        logger.info(f"Deleting incident alert {inc.id} by admin user {current_user.id}")
        # Disassociate any reports pointing to this incident so reports are preserved
        rep_stmt = select(Report).filter(
            or_(
                Report.incident_id == inc.id,
                cast(Report.incident_id, String) == target_hex,
                cast(Report.incident_id, String) == str(inc.id)
            )
        )
        rep_res = await db.execute(rep_stmt)
        for rep in rep_res.scalars().all():
            rep.incident_id = None
        
        # Clean up any IncidentPerson rows
        del_ip_stmt = delete(IncidentPerson).where(
            or_(
                IncidentPerson.incident_id == id,
                cast(IncidentPerson.incident_id, String) == target_hex,
                cast(IncidentPerson.incident_id, String) == str(id)
            )
        )
        await db.execute(del_ip_stmt)

        # Disassociate detected events
        de_stmt = select(DetectedEvent).filter(
            or_(
                DetectedEvent.incident_id == id,
                cast(DetectedEvent.incident_id, String) == target_hex,
                cast(DetectedEvent.incident_id, String) == str(id)
            )
        )
        de_res = await db.execute(de_stmt)
        for de in de_res.scalars().all():
            de.incident_id = None

        del_inc_stmt = delete(Incident).where(
            or_(
                Incident.id == id,
                cast(Incident.id, String) == target_hex,
                cast(Incident.id, String) == str(id)
            )
        )
        await db.execute(del_inc_stmt)
        await db.commit()
        return {"detail": "Security alert deleted successfully"}

    # 2. Search Event table
    evt_stmt = select(Event).filter(
        or_(
            Event.id == id,
            cast(Event.id, String) == target_hex,
            cast(Event.id, String) == str(id)
        )
    )
    evt_res = await db.execute(evt_stmt)
    event_obj = evt_res.scalars().first()

    if event_obj:
        logger.info(f"Deleting event alert {event_obj.id} by admin user {current_user.id}")
        del_et_stmt = delete(EventTrack).where(
            or_(
                EventTrack.event_id == id,
                cast(EventTrack.event_id, String) == target_hex,
                cast(EventTrack.event_id, String) == str(id)
            )
        )
        await db.execute(del_et_stmt)

        del_evt_stmt = delete(Event).where(
            or_(
                Event.id == id,
                cast(Event.id, String) == target_hex,
                cast(Event.id, String) == str(id)
            )
        )
        await db.execute(del_evt_stmt)
        await db.commit()
        return {"detail": "Security alert deleted successfully"}

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Security alert not found."
    )
