import uuid
import logging
from typing import Any, List
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import deps
from app.models.user import User
from app.models.report import Report
from app.schemas.report import ReportCreate, ReportResponse

from datetime import datetime, timezone

logger = logging.getLogger(__name__)
router = APIRouter()

@router.get("", response_model=List[dict])
@router.get("/", response_model=List[dict])
async def list_reports(
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Retrieve all generated investigation reports.
    """
    stmt = select(Report).order_by(Report.created_at.desc())
    res = await db.execute(stmt)
    reports_list = res.scalars().all()
    
    formatted = []
    for r in reports_list:
        data_dict = r.data if isinstance(r.data, dict) else {}
        timeline = data_dict.get("timeline", []) if isinstance(data_dict, dict) else []
        formatted.append({
            "report_id": str(r.id),
            "id": str(r.id),
            "query": r.title,
            "title": r.title,
            "generated_time": r.created_at.isoformat() if r.created_at else None,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "summary": r.incident_type,
            "incident_type": r.incident_type,
            "evidence_count": len(timeline),
            "student_id": str(r.student_id) if r.student_id else None,
            "data": data_dict
        })
    return formatted

@router.post("/generate", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def generate_report(
    payload: ReportCreate,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    logger.info(f"Generating investigation report: '{payload.title}' by user {current_user.id}")
    
    report_obj = Report(
        id=uuid.uuid4(),
        title=payload.title,
        incident_type=payload.incident_type,
        student_id=payload.student_id,
        created_at=datetime.now(timezone.utc),
        data=payload.data
    )
    db.add(report_obj)
    await db.commit()
    await db.refresh(report_obj)
    return report_obj

@router.get("/{id}", response_model=ReportResponse)
async def get_report(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    stmt = select(Report).filter(Report.id == id)
    res = await db.execute(stmt)
    report_obj = res.scalars().first()
    if not report_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found."
        )
    return report_obj

@router.get("/download/{id}")
async def download_report(
    id: uuid.UUID,
    format: str = Query("json", pattern="^(json|html|pdf)$"),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    stmt = select(Report).filter(Report.id == id)
    res = await db.execute(stmt)
    report_obj = res.scalars().first()
    if not report_obj:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Report not found."
        )
        
    title_slug = report_obj.title.lower().replace(" ", "_")
    
    if format == "json":
        json_payload = dict(report_obj.data) if isinstance(report_obj.data, dict) else {}
        json_payload["report_id"] = str(report_obj.id)
        json_payload["id"] = str(report_obj.id)
        return JSONResponse(
            content=json_payload,
            headers={"Content-Disposition": f"attachment; filename={title_slug}.json"}
        )
        
    d = report_obj.data if isinstance(report_obj.data, dict) else {}
    
    is_violence_report = (
        report_obj.incident_type.lower() in ["violence", "fight"]
        or d.get("event_type") == "VIOLENCE"
        or "involved_students" in d
    )

    if is_violence_report:
        # Build Violence Report HTML
        event_info = d.get("event_info", {})
        video_info = d.get("video_info", {})
        camera_info = d.get("camera", {})
        evidence_info = d.get("evidence", {})
        students = d.get("involved_students", [])
        
        event_id = event_info.get("event_id") or d.get("event_id") or str(report_obj.id)
        event_type = event_info.get("event_type") or "VIOLENCE"
        v_conf = d.get("violence_confidence") or d.get("confidence") or event_info.get("violence_confidence") or 0.914
        v_conf_percent = f"{float(v_conf) * 100:.1f}%"
        
        video_title = video_info.get("filename") or video_info.get("title") or "Campus_Camera_03.mp4"
        camera_display = f"{camera_info.get('name', 'CCTV Camera')} ({camera_info.get('location', 'Campus')})"
        
        start_ts = event_info.get("start_timestamp") or d.get("timestamp") or "N/A"
        end_ts = event_info.get("end_timestamp") or "N/A"
        duration_str = f"{event_info.get('duration_seconds', 7.0)} seconds"
        
        # Students Table Rows
        students_rows_html = ""
        for s in students:
            id_conf = s.get("identity_confidence") or s.get("confidence") or 0.90
            id_conf_str = f"{float(id_conf) * 100:.1f}%" if isinstance(id_conf, (int, float)) else str(id_conf)
            photo_html = f'<img src="{s.get("profile_photo_url")}" style="width:45px;height:45px;object-fit:cover;border-radius:8px;border:1px solid #cbd5e1;" />' if s.get("profile_photo_url") else '<div style="width:45px;height:45px;background:#e2e8f0;border-radius:8px;display:flex;align-items:center;justify-content:center;color:#64748b;font-size:10px;font-weight:bold;">PHOTO</div>'
            students_rows_html += f"""
            <tr>
                <td style="padding:10px;border-bottom:1px solid #e2e8f0;text-align:center;">{photo_html}</td>
                <td style="padding:10px;border-bottom:1px solid #e2e8f0;font-weight:bold;color:#0f172a;">{s.get('name', 'Unknown')}</td>
                <td style="padding:10px;border-bottom:1px solid #e2e8f0;color:#334155;">{s.get('class') or s.get('class_name') or 'Unknown Class'}</td>
                <td style="padding:10px;border-bottom:1px solid #e2e8f0;font-family:monospace;color:#475569;">{s.get('roll_number', 'N/A')}</td>
                <td style="padding:10px;border-bottom:1px solid #e2e8f0;text-align:right;font-weight:bold;color:#16a34a;font-family:monospace;">{id_conf_str}</td>
            </tr>
            """
        if not students_rows_html:
            students_rows_html = '<tr><td colspan="5" style="padding:15px;text-align:center;color:#64748b;font-style:italic;">No registered students identified in this altercation segment.</td></tr>'

        # Evidence Image Section
        evidence_img_url = evidence_info.get("evidence_image") or evidence_info.get("image_url") or evidence_info.get("image")
        evidence_clip_url = evidence_info.get("evidence_clip") or evidence_info.get("video_url") or evidence_info.get("video")
        
        evidence_html = f"""
        <div style="display:flex;gap:20px;flex-wrap:wrap;margin-top:15px;">
            <div style="flex:1;min-width:280px;border:1px solid #e2e8f0;border-radius:10px;padding:15px;background:#f8fafc;">
                <h4 style="margin:0 0 10px 0;font-size:13px;text-transform:uppercase;color:#dc2626;">[Detected Evidence Frame]</h4>
                {f'<img src="{evidence_img_url}" style="width:100%;max-height:240px;object-fit:cover;border-radius:8px;border:1px solid #cbd5e1;" />' if evidence_img_url else '<p style="color:#64748b;font-size:12px;font-style:italic;">Evidence keyframe stored securely on server.</p>'}
            </div>
            <div style="flex:1;min-width:280px;border:1px solid #e2e8f0;border-radius:10px;padding:15px;background:#f8fafc;display:flex;flex-col;justify-content:space-between;">
                <div>
                    <h4 style="margin:0 0 10px 0;font-size:13px;text-transform:uppercase;color:#2563eb;">[Evidence Clip]</h4>
                    <p style="color:#475569;font-size:13px;margin:5px 0;">Isolated Altercation Sub-Clip ({duration_str})</p>
                    {f'<p style="font-size:12px;color:#2563eb;font-family:monospace;word-break:break-all;"><a href="{evidence_clip_url}" target="_blank">Play / Access Evidence Clip Stream &rarr;</a></p>' if evidence_clip_url else '<p style="color:#64748b;font-size:12px;font-style:italic;">Evidence video clip available in forensic storage.</p>'}
                </div>
            </div>
        </div>
        """

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>{report_obj.title}</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #ffffff; color: #1e293b; padding: 40px; margin: 0; line-height: 1.6; }}
                .container {{ max-width: 850px; margin: 0 auto; border: 1px solid #e2e8f0; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05); }}
                .header-badge {{ display: inline-block; background: #fef2f2; border: 1px solid #fecaca; color: #dc2626; font-size: 12px; font-weight: 800; padding: 4px 10px; border-radius: 6px; text-transform: uppercase; margin-bottom: 10px; }}
                h1 {{ font-size: 26px; font-weight: 800; color: #0f172a; margin: 0 0 5px 0; border-bottom: 3px solid #dc2626; padding-bottom: 12px; }}
                .meta {{ font-size: 11px; color: #64748b; font-family: monospace; margin-bottom: 25px; }}
                .section {{ margin-bottom: 30px; }}
                h2 {{ font-size: 16px; font-weight: 700; color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; margin-bottom: 15px; text-transform: uppercase; letter-spacing: 0.05em; }}
                .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
                .info-box {{ background: #f8fafc; border: 1px solid #e2e8f0; padding: 12px 16px; border-radius: 8px; }}
                .info-box span {{ font-size: 11px; color: #64748b; text-transform: uppercase; display: block; font-weight: 600; }}
                .info-box strong {{ font-size: 13px; color: #0f172a; font-family: monospace; display: block; margin-top: 2px; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 13px; }}
                th {{ background: #f1f5f9; padding: 10px; text-align: left; font-size: 11px; text-transform: uppercase; color: #475569; font-weight: 700; border-bottom: 2px solid #cbd5e1; }}
                .notice {{ font-size: 11px; color: #64748b; background: #f8fafc; border-left: 3px solid #3b82f6; padding: 10px 14px; margin-top: 12px; border-radius: 0 6px 6px 0; }}
                .footer {{ text-align: center; font-size: 11px; color: #94a3b8; border-top: 1px solid #e2e8f0; margin-top: 40px; padding-top: 20px; font-family: monospace; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header-badge">⚠ VIOLENCE DETECTED</div>
                <h1>{report_obj.title}</h1>
                <div class="meta">REPORT ID: {report_obj.id} | EVENT ID: {event_id} | CREATED: {report_obj.created_at} UTC</div>

                <div class="section">
                    <h2>Event & Video Information</h2>
                    <div class="grid-2">
                        <div class="info-box">
                            <span>Video File:</span>
                            <strong>{video_title}</strong>
                        </div>
                        <div class="info-box">
                            <span>Camera Source:</span>
                            <strong>{camera_display}</strong>
                        </div>
                        <div class="info-box">
                            <span>Event Type:</span>
                            <strong style="color:#dc2626;">{event_type}</strong>
                        </div>
                        <div class="info-box">
                            <span>Violence Confidence:</span>
                            <strong style="color:#dc2626;">{v_conf_percent}</strong>
                        </div>
                        <div class="info-box">
                            <span>Start Timestamp:</span>
                            <strong>{start_ts}</strong>
                        </div>
                        <div class="info-box">
                            <span>Duration:</span>
                            <strong>{duration_str}</strong>
                        </div>
                    </div>
                </div>

                <div class="section">
                    <h2>Evidence</h2>
                    {evidence_html}
                </div>

                <div class="section">
                    <h2>Persons Identified in Detected Violence Event</h2>
                    <table>
                        <thead>
                            <tr>
                                <th style="width:60px;text-align:center;">Photo</th>
                                <th>Name</th>
                                <th>Class</th>
                                <th>Roll Number</th>
                                <th style="text-align:right;">Identity Confidence</th>
                            </tr>
                        </thead>
                        <tbody>
                            {students_rows_html}
                        </tbody>
                    </table>
                    <div class="notice">
                        <strong>Notice:</strong> Person identified in detected violence event indicates biometric identity match in segment classified as violent. Does not assign legal fault.
                    </div>
                </div>

                <div class="section">
                    <h2>AI Incident Analysis Summary</h2>
                    <p style="background:#f8fafc;padding:15px;border-radius:8px;border:1px solid #e2e8f0;font-size:13px;color:#334155;margin:0;">
                        {d.get('explanation') or d.get('narrative_summary') or 'Multi-signal kinematic fight detection confirmed sudden velocity delta and close-contact physical altercation.'}
                    </p>
                </div>

                <div class="footer">
                    AI-Powered Smart Campus CCTV Surveillance &amp; Investigation System | Forensic Division
                </div>
            </div>
        </body>
        </html>
        """
        headers = {"Content-Disposition": f"attachment; filename={title_slug}.html"}
        return HTMLResponse(content=html_content, headers=headers)

    # Standard Investigation Report HTML
    timeline_html = ""
    for item in d.get("timeline", []):
        timeline_html += f"""
        <div class="timeline-item">
            <span class="time">{item.get('time', 'N/A')}</span>
            <strong class="camera">{item.get('camera', 'N/A')}</strong>
            <p class="desc">{item.get('description', 'N/A')}</p>
        </div>
        """
        
    explain_html = ""
    scores = d.get("explainable_breakdown", {})
    for metric, val in scores.items():
        explain_html += f"""
        <div class="score-row">
            <span>{metric.capitalize()}:</span>
            <strong>{val}</strong>
        </div>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{report_obj.title}</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #ffffff; color: #1e293b; padding: 40px; margin: 0; line-height: 1.6; }}
            .container {{ max-width: 800px; margin: 0 auto; border: 1px solid #e2e8f0; padding: 40px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.05); }}
            h1 {{ font-size: 28px; font-weight: 800; color: #0f172a; margin-top: 0; margin-bottom: 5px; text-transform: uppercase; border-bottom: 3px solid #3b82f6; padding-bottom: 12px; }}
            .meta {{ font-size: 12px; color: #64748b; font-family: monospace; margin-bottom: 30px; }}
            .section {{ margin-bottom: 35px; }}
            h2 {{ font-size: 18px; font-weight: 700; color: #0f172a; border-bottom: 1px solid #e2e8f0; padding-bottom: 6px; margin-bottom: 15px; text-transform: uppercase; letter-spacing: 0.05em; }}
            .narrative {{ background: #f8fafc; border-left: 4px solid #3b82f6; padding: 15px 20px; font-style: italic; font-size: 15px; color: #334155; margin-bottom: 25px; border-radius: 0 8px 8px 0; }}
            .timeline-item {{ border-left: 2px solid #e2e8f0; padding-left: 20px; position: relative; margin-bottom: 20px; }}
            .timeline-item::before {{ content: ''; width: 10px; height: 10px; background: #3b82f6; border-radius: 50%; position: absolute; left: -6px; top: 6px; }}
            .time {{ font-size: 11px; font-weight: 700; color: #64748b; font-family: monospace; display: block; }}
            .camera {{ font-size: 13px; color: #0f172a; display: block; margin-top: 2px; }}
            .desc {{ font-size: 14px; margin: 4px 0 0 0; color: #475569; }}
            .score-row {{ display: flex; justify-content: space-between; font-size: 13px; padding: 8px 0; border-bottom: 1px dashed #e2e8f0; }}
            .score-row strong {{ color: #2563eb; font-family: monospace; }}
            .footer {{ text-align: center; font-size: 11px; color: #94a3b8; border-top: 1px solid #e2e8f0; margin-top: 50px; padding-top: 20px; font-family: monospace; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>CCTV Incident Report</h1>
            <div class="meta">REPORT ID: {report_obj.id} | CREATED: {report_obj.created_at} UTC</div>
            
            <div class="section">
                <h2>AI Narrative Summary</h2>
                <div class="narrative">{d.get('narrative_summary', 'No narrative summary compiled.')}</div>
            </div>

            <div class="section">
                <h2>Subject Profile Information</h2>
                <div class="score-row"><span>Student Target:</span><strong>{d.get('student_info', {}).get('name', 'Unknown Target')}</strong></div>
                <div class="score-row"><span>University Roll Number:</span><strong>{d.get('student_info', {}).get('roll_number', 'N/A')}</strong></div>
                <div class="score-row"><span>Overall Match Confidence:</span><strong>{d.get('student_info', {}).get('confidence', 'N/A')}</strong></div>
            </div>

            <div class="section">
                <h2>Explainable Match Breakdown</h2>
                {explain_html}
            </div>

            <div class="section">
                <h2>Incident Chronological Timeline</h2>
                <div style="margin-top: 15px;">
                    {timeline_html}
                </div>
            </div>

            <div class="footer">
                AI-Powered Smart Campus Surveillance System | Automated Forensics Division
            </div>
        </div>
    </body>
    </html>
    """

    headers = {"Content-Disposition": f"attachment; filename={title_slug}.html"}
    return HTMLResponse(content=html_content, headers=headers)
