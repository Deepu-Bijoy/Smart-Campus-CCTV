import os
import zipfile
import uuid
import shutil
import hashlib
from datetime import datetime, timezone
import pandas as pd
import logging
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api import deps
from app.models.user import User
from app.models.student import Student, StudentPhoto, StudentFaceSession
from app.models.bulk_import import BulkImportJob
from app.schemas.bulk_import import BulkImportJobResponse
from app.tasks.bulk_tasks import bulk_enroll_faces_task

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/import", response_model=BulkImportJobResponse, status_code=status.HTTP_201_CREATED)
async def import_students_spreadsheet(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    logger.info(f"User {current_user.id} importing student list: {file.filename}")
    
    ext = os.path.splitext(file.filename)[1].lower()
    try:
        if ext in [".csv"]:
            df = pd.read_csv(file.file)
        elif ext in [".xlsx", ".xls"]:
            df = pd.read_excel(file.file)
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported spreadsheet format. Only CSV and Excel (.xlsx) are supported."
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse spreadsheet file: {str(e)}"
        )

    required_cols = ["roll_number", "name", "department", "programme", "year", "semester", "section", "email"]
    df.columns = [c.lower().strip().replace(" ", "_") for c in df.columns]
    
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required columns in spreadsheet: {', '.join(missing_cols)}"
        )

    job = BulkImportJob(
        id=uuid.uuid4(),
        status="pending",
        total_records=len(df),
        processed_records=0,
        successful_records=0,
        failed_records=0,
        report={"summary": "Spreadsheet parsed.", "errors": [], "success_items": []},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    successful = 0
    failed = 0
    errors_log = []
    success_items = []

    for idx, row in df.iterrows():
        roll_number = str(row.get("roll_number", "")).strip()
        name = str(row.get("name", "")).strip()
        email = str(row.get("email", "")).strip()
        dept = str(row.get("department", "")).strip()
        prog = str(row.get("programme", "")).strip()
        year_val = row.get("year")
        sem_val = row.get("semester")
        sect = str(row.get("section", "A")).strip()
        phone = str(row.get("phone", "")) if "phone" in df.columns else None

        if not roll_number or not name or not email:
            failed += 1
            errors_log.append({"row": idx + 2, "error": "Missing Roll Number, Name, or Email fields."})
            continue

        if "@" not in email:
            failed += 1
            errors_log.append({"row": idx + 2, "roll_number": roll_number, "error": "Invalid email address format."})
            continue

        try:
            dup_roll = await db.execute(select(Student).filter(Student.university_roll_number == roll_number))
            if dup_roll.scalars().first():
                failed += 1
                errors_log.append({"row": idx + 2, "roll_number": roll_number, "error": "Roll Number already exists."})
                continue

            dup_email = await db.execute(select(Student).filter(Student.email == email))
            if dup_email.scalars().first():
                failed += 1
                errors_log.append({"row": idx + 2, "roll_number": roll_number, "error": "Email address already registered."})
                continue

            student = Student(
                university_roll_number=roll_number,
                name=name,
                email=email,
                department=dept,
                programme=prog,
                year=int(year_val) if year_val else 1,
                semester=int(sem_val) if sem_val else 1,
                section=sect,
                phone=phone,
                status="active"
            )
            db.add(student)
            await db.commit()
            
            db_session = StudentFaceSession(student_id=student.id, status="pending")
            db.add(db_session)
            await db.commit()

            successful += 1
            success_items.append({"roll_number": roll_number, "name": name})

        except Exception as ex:
            failed += 1
            errors_log.append({"row": idx + 2, "roll_number": roll_number, "error": f"Database error: {str(ex)}"})
            continue

    job.status = "completed"
    job.processed_records = len(df)
    job.successful_records = successful
    job.failed_records = failed
    job.report = {
        "summary": "Spreadsheet import completed.",
        "errors": errors_log,
        "success_items": success_items
    }
    await db.commit()
    await db.refresh(job)

    return job

@router.post("/import/photos", status_code=status.HTTP_200_OK)
async def import_students_photos_dataset(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    logger.info(f"User {current_user.id} uploading bulk dataset photos: {file.filename}")
    
    if not file.filename.endswith(".zip"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Photos dataset must be uploaded as a compressed ZIP file."
        )

    temp_zip_path = f"storage/temp_{uuid.uuid4()}.zip"
    os.makedirs("storage", exist_ok=True)
    with open(temp_zip_path, "wb") as f_out:
        f_out.write(await file.read())

    temp_dir = f"storage/temp_dataset_{uuid.uuid4()}"
    os.makedirs(temp_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
            zip_ref.extractall(temp_dir)
    except Exception as e:
        shutil.rmtree(temp_dir, ignore_errors=True)
        if os.path.exists(temp_zip_path):
            os.remove(temp_zip_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to unzip dataset archive: {str(e)}"
        )

    matched_count = 0
    errors_log = []
    
    allowed_views = {"front", "left", "right", "up", "down", "masked", "glasses"}
    allowed_exts = {".jpg", ".jpeg", ".png"}

    for root, dirs, files in os.walk(temp_dir):
        for sub_dir in dirs:
            roll_number = sub_dir.strip()
            
            stmt = select(Student).filter(Student.university_roll_number == roll_number)
            res = await db.execute(stmt)
            student = res.scalars().first()
            if not student:
                errors_log.append({"folder": roll_number, "error": "No matching student record found for this Roll Number."})
                continue

            sub_dir_path = os.path.join(root, sub_dir)
            for f in os.listdir(sub_dir_path):
                f_ext = os.path.splitext(f)[1].lower()
                if f_ext not in allowed_exts:
                    continue

                view = "unknown"
                fn_lower = f.lower()
                for v in allowed_views:
                    if v in fn_lower:
                        view = v
                        break
                
                permanent_dir = os.path.join("storage", "students", str(student.id), view)
                os.makedirs(permanent_dir, exist_ok=True)
                
                new_fn = f"{uuid.uuid4()}{f_ext}"
                dest_path = os.path.join(permanent_dir, new_fn)
                
                src_path = os.path.join(sub_dir_path, f)
                shutil.copy(src_path, dest_path)
                
                with open(dest_path, "rb") as f_read:
                    content = f_read.read()
                    md5_hash = hashlib.md5(content).hexdigest()
                    file_size = len(content)

                dup_photo = await db.execute(
                    select(StudentPhoto).filter(
                        StudentPhoto.student_id == student.id,
                        StudentPhoto.md5_hash == md5_hash
                    )
                )
                if dup_photo.scalars().first():
                    os.remove(dest_path)
                    continue

                db_photo = StudentPhoto(
                    student_id=student.id,
                    photo_path=dest_path,
                    view=view,
                    file_size=file_size,
                    mime_type="image/jpeg" if f_ext in [".jpg", ".jpeg"] else "image/png",
                    md5_hash=md5_hash,
                    metadata_json={"original_filename": f}
                )
                db.add(db_photo)
                matched_count += 1

            session_stmt = select(StudentFaceSession).filter(StudentFaceSession.student_id == student.id)
            sess_res = await db.execute(session_stmt)
            session = sess_res.scalars().first()
            if session:
                session.status = "completed"
                await db.commit()

    await db.commit()

    shutil.rmtree(temp_dir, ignore_errors=True)
    if os.path.exists(temp_zip_path):
        os.remove(temp_zip_path)

    return {
        "summary": "Bulk dataset photos import processed.",
        "matched_photos_count": matched_count,
        "errors": errors_log
    }

@router.post("/import/enroll", response_model=BulkImportJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_bulk_face_enrollment(
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    logger.info(f"User {current_user.id} triggering batch face enrollment")
    
    job = BulkImportJob(
        id=uuid.uuid4(),
        status="pending",
        total_records=0,
        processed_records=0,
        successful_records=0,
        failed_records=0,
        report={"summary": "Pending background job initialization."},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc)
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    bulk_enroll_faces_task.delay(str(job.id))
    
    return job

@router.get("/import/status/{job_id}", response_model=BulkImportJobResponse)
async def get_import_job_status(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    result = await db.execute(select(BulkImportJob).filter(BulkImportJob.id == job_id))
    job = result.scalars().first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bulk Import Job not found."
        )
    return job

@router.put("/import/cancel/{job_id}", response_model=BulkImportJobResponse)
async def cancel_import_job(
    job_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    result = await db.execute(select(BulkImportJob).filter(BulkImportJob.id == job_id))
    job = result.scalars().first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bulk Import Job not found."
        )
    job.status = "cancelled"
    await db.commit()
    await db.refresh(job)
    return job

@router.get("/import/report/{job_id}")
async def get_import_job_report(
    job_id: uuid.UUID,
    format: str = "json",
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    result = await db.execute(select(BulkImportJob).filter(BulkImportJob.id == job_id))
    job = result.scalars().first()
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Bulk Import Job not found."
        )

    if format.lower() == "csv":
        errors = job.report.get("errors", [])
        import csv
        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Row", "Roll Number", "Error Reason"])
        for err in errors:
            writer.writerow([err.get("row", ""), err.get("roll_number", ""), err.get("error", "")])
        
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename=import_report_{job_id}.csv"}
        )

    return job.report
