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
        return JSONResponse(
            content=report_obj.data,
            headers={"Content-Disposition": f"attachment; filename={title_slug}.json"}
        )
        
    d = report_obj.data
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
