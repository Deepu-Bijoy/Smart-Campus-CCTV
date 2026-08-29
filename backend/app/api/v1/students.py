import uuid
import logging
import os
import hashlib
import shutil
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import or_, desc, asc, func

from app.api import deps
from app.models.user import User
from app.models.student import Student, StudentPhoto, StudentFaceSession
from app.models.face_embedding import StudentFaceEmbedding
from app.pipeline.face_engine import FaceEnrollmentEngine
from app.services.vector_store import QdrantVectorStore
from app.schemas.student import (
    StudentCreate,
    StudentUpdate,
    StudentResponse,
    StudentListResponse,
    StudentPhotoResponse,
    EnrollmentSummaryResponse,
    EnrollmentStatusResponse
)

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("", response_model=StudentResponse, status_code=status.HTTP_201_CREATED)
async def create_student(
    payload: StudentCreate,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Register a new student record in the management database.
    """
    logger.info(f"User {current_user.id} creating student record: Roll No={payload.university_roll_number}")
    
    # 1. Check duplicate roll number
    dup_roll = await db.execute(
        select(Student).filter(Student.university_roll_number == payload.university_roll_number)
    )
    if dup_roll.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Student with University Roll Number {payload.university_roll_number} is already registered."
        )
        
    # 2. Check duplicate email
    dup_email = await db.execute(
        select(Student).filter(Student.email == payload.email)
    )
    if dup_email.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Student with Email {payload.email} is already registered."
        )
        
    db_student = Student(**payload.model_dump())
    db.add(db_student)
    await db.commit()
    await db.refresh(db_student)
    
    # Initialize a default face enrollment session
    db_session = StudentFaceSession(student_id=db_student.id, status="pending")
    db.add(db_session)
    await db.commit()
    
    await db.refresh(db_student)
    return db_student

@router.get("", response_model=StudentListResponse)
async def list_students(
    skip: int = 0,
    limit: int = 10,
    query: Optional[str] = None,
    department: Optional[str] = None,
    programme: Optional[str] = None,
    year: Optional[int] = None,
    semester: Optional[int] = None,
    status_filter: Optional[str] = None,
    sort_by: str = "created_at",
    sort_order: str = "desc",
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Get a paginated, searchable, and filtered list of registered students.
    """
    stmt = select(Student)
    
    # Apply query filters
    if query:
        search_pattern = f"%{query}%"
        stmt = stmt.filter(
            or_(
                Student.name.ilike(search_pattern),
                Student.university_roll_number.ilike(search_pattern)
            )
        )
    if department:
        stmt = stmt.filter(Student.department == department)
    if programme:
        stmt = stmt.filter(Student.programme == programme)
    if year is not None:
        stmt = stmt.filter(Student.year == year)
    if semester is not None:
        stmt = stmt.filter(Student.semester == semester)
    if status_filter:
        stmt = stmt.filter(Student.status == status_filter)
        
    # Get total count (before offset/limit)
    count_stmt = select(func.count()).select_from(stmt.subquery())
    count_res = await db.execute(count_stmt)
    total = count_res.scalar() or 0
    
    # Apply sorting
    allowed_sort_fields = {"name", "university_roll_number", "created_at", "updated_at", "department"}
    field_to_sort = sort_by if sort_by in allowed_sort_fields else "created_at"
    sort_attr = getattr(Student, field_to_sort)
    stmt = stmt.order_by(desc(sort_attr) if sort_order.lower() == "desc" else asc(sort_attr))
    
    # Apply pagination
    stmt = stmt.offset(skip).limit(limit)
    result = await db.execute(stmt)
    items = result.scalars().all()
    
    return {"total": total, "items": items}

@router.get("/{id}", response_model=StudentResponse)
async def get_student(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Retrieve details of a single student by ID.
    """
    result = await db.execute(select(Student).filter(Student.id == id))
    student = result.scalars().first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {id} not found."
        )
    return student

@router.put("/{id}", response_model=StudentResponse)
async def update_student(
    id: uuid.UUID,
    payload: StudentUpdate,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Update a student's profile information.
    """
    result = await db.execute(select(Student).filter(Student.id == id))
    student = result.scalars().first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {id} not found."
        )
        
    # Check email duplicate if updating
    if payload.email and payload.email != student.email:
        dup_email = await db.execute(select(Student).filter(Student.email == payload.email))
        if dup_email.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Email {payload.email} is already in use by another student."
            )
            
    # Apply updates
    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(student, key, value)
        
    await db.commit()
    await db.refresh(student)
    return student

@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> None:
    """
    Delete a student record and remove all physical photo attachments from disk.
    """
    result = await db.execute(select(Student).filter(Student.id == id))
    student = result.scalars().first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {id} not found."
        )
        
    # Cleanup physical storage folder
    student_dir = os.path.join("storage", "students", str(id))
    if os.path.exists(student_dir):
        try:
            shutil.rmtree(student_dir)
            logger.info(f"Removed student photos storage path: {student_dir}")
        except Exception as e:
            logger.error(f"Failed to remove storage directory {student_dir}: {str(e)}")
            
    # Cleanup Qdrant vectors
    try:
        qdrant_store = QdrantVectorStore()
        qdrant_store.delete_face_embeddings_by_student(id)
    except Exception as qe:
        logger.error(f"Failed to clean up Qdrant vectors for student {id}: {str(qe)}")
            
    await db.delete(student)
    await db.commit()
    return

@router.post("/{id}/photos", response_model=List[StudentPhotoResponse], status_code=status.HTTP_201_CREATED)
async def upload_student_photos(
    id: uuid.UUID,
    files: List[UploadFile] = File(...),
    views: Optional[List[str]] = Form(None),
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Upload photos of the student captured from different angles.
    """
    # 1. Validate student existence
    result = await db.execute(select(Student).filter(Student.id == id))
    student = result.scalars().first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {id} not found."
        )
        
    allowed_mime_types = {"image/jpeg", "image/png", "image/jpg"}
    allowed_views = {"front", "left", "right", "up", "down", "masked", "glasses", "unknown"}
    max_size = 5 * 1024 * 1024  # 5MB limit
    
    uploaded_photos = []
    
    for idx, file in enumerate(files):
        # Validate mime type
        if file.content_type not in allowed_mime_types:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid file type {file.content_type} for file {file.filename}. Only JPEG and PNG are allowed."
            )
            
        content = await file.read()
        file_size = len(content)
        
        # Validate maximum size
        if file_size > max_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File {file.filename} exceeds the 5MB size limit."
            )
            
        # Calculate MD5 hash
        md5_hash = hashlib.md5(content).hexdigest()
        
        # Check duplicate hash for this student
        dup_check = await db.execute(
            select(StudentPhoto).filter(
                StudentPhoto.student_id == id,
                StudentPhoto.md5_hash == md5_hash
            )
        )
        if dup_check.scalars().first():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate photo: File {file.filename} matches an already uploaded photo for this student."
            )
            
        # Determine view orientation
        view = "unknown"
        if views and idx < len(views):
            v_val = views[idx].lower().strip()
            if v_val in allowed_views:
                view = v_val
        else:
            # Fallback filename match
            fn_lower = file.filename.lower()
            for v in allowed_views:
                if v != "unknown" and v in fn_lower:
                    view = v
                    break
                    
        # Save photo to local disk
        student_view_dir = os.path.join("storage", "students", str(id), view)
        os.makedirs(student_view_dir, exist_ok=True)
        
        file_ext = os.path.splitext(file.filename)[1]
        if not file_ext:
            file_ext = ".jpg" if file.content_type == "image/jpeg" else ".png"
        photo_filename = f"{uuid.uuid4()}{file_ext}"
        photo_path = os.path.join(student_view_dir, photo_filename)
        
        with open(photo_path, "wb") as f_out:
            f_out.write(content)
            
        # Create database record
        db_photo = StudentPhoto(
            student_id=id,
            photo_path=photo_path,
            view=view,
            file_size=file_size,
            mime_type=file.content_type,
            md5_hash=md5_hash,
            metadata_json={"original_filename": file.filename}
        )
        db.add(db_photo)
        uploaded_photos.append(db_photo)
        
    await db.commit()
    for p in uploaded_photos:
        await db.refresh(p)
        
    # Update face session status to completed if we have uploaded photos
    session_result = await db.execute(
        select(StudentFaceSession).filter(
            StudentFaceSession.student_id == id,
            StudentFaceSession.status == "pending"
        )
    )
    face_session = session_result.scalars().first()
    if face_session:
        face_session.status = "completed"
        await db.commit()
        
    return uploaded_photos

@router.get("/{id}/photos", response_model=List[StudentPhotoResponse])
async def get_student_photos(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Retrieve all uploaded photos for a student.
    """
    # Validate student existence
    result = await db.execute(select(Student).filter(Student.id == id))
    if not result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {id} not found."
        )
        
    photos_result = await db.execute(
        select(StudentPhoto).filter(StudentPhoto.student_id == id)
    )
    return photos_result.scalars().all()

@router.delete("/{id}/photos", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student_photos(
    id: uuid.UUID,
    view: Optional[str] = None,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> None:
    """
    Remove all student photos, or filter by a specific view orientation.
    """
    result = await db.execute(select(Student).filter(Student.id == id))
    if not result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {id} not found."
        )
        
    stmt = select(StudentPhoto).filter(StudentPhoto.student_id == id)
    if view:
        stmt = stmt.filter(StudentPhoto.view == view.lower().strip())
        
    photos_res = await db.execute(stmt)
    photos = photos_res.scalars().all()
    
    for photo in photos:
        # Delete from disk
        if os.path.exists(photo.photo_path):
            try:
                os.remove(photo.photo_path)
            except Exception as e:
                logger.error(f"Failed to remove file {photo.photo_path}: {str(e)}")
                
        # Cleanup Qdrant face embedding
        try:
            qdrant_store = QdrantVectorStore()
            qdrant_store.delete_face_embedding_by_photo(photo.id)
        except Exception as qe:
            logger.error(f"Failed to clean up Qdrant vector for photo {photo.id}: {str(qe)}")
                
        # If we delete a view folder, we can clean it up if it's empty
        parent_dir = os.path.dirname(photo.photo_path)
        await db.delete(photo)
        
        # Clean parent directory if empty
        if os.path.exists(parent_dir) and not os.listdir(parent_dir):
            try:
                os.rmdir(parent_dir)
            except Exception:
                pass
                
    await db.commit()
    return

@router.delete("/{student_id}/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_specific_student_photo(
    student_id: uuid.UUID,
    photo_id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> None:
    """
    Delete a specific uploaded photo of a student, clean its database record,
    delete its local file on disk, clean its face embedding in Qdrant,
    and update the student's enrollment status if no photos remain.
    """
    # 1. Fetch student
    student_res = await db.execute(select(Student).filter(Student.id == student_id))
    student = student_res.scalars().first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {student_id} not found."
        )
        
    # 2. Fetch photo
    photo_res = await db.execute(
        select(StudentPhoto).filter(
            StudentPhoto.id == photo_id,
            StudentPhoto.student_id == student_id
        )
    )
    photo = photo_res.scalars().first()
    if not photo:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Photo not found or doesn't belong to this student."
        )
        
    # Atomic deletion block
    try:
        # Delete from disk
        if os.path.exists(photo.photo_path):
            os.remove(photo.photo_path)
            
        # Clean parent directory if empty
        parent_dir = os.path.dirname(photo.photo_path)
        if os.path.exists(parent_dir) and not os.listdir(parent_dir):
            try:
                os.rmdir(parent_dir)
            except Exception:
                pass
                
        # Remove from Qdrant
        try:
            qdrant_store = QdrantVectorStore()
            qdrant_store.delete_face_embedding_by_photo(photo_id)
        except Exception as qe:
            logger.error(f"Failed to delete face embedding from Qdrant: {str(qe)}")
            
        # Remove from DB
        emb_check = await db.execute(
            select(StudentFaceEmbedding).filter(StudentFaceEmbedding.photo_id == photo_id)
        )
        emb = emb_check.scalars().first()
        if emb:
            await db.delete(emb)
            
        # Remove photo from relationship (triggers delete-orphan)
        if photo in student.photos:
            student.photos.remove(photo)
        else:
            await db.delete(photo)
            
        await db.commit()
        
        # Check if any face embeddings remain for the student
        remaining_check = await db.execute(
            select(StudentFaceEmbedding).filter(StudentFaceEmbedding.student_id == student_id)
        )
        remaining = remaining_check.scalars().all()
        if not remaining:
            student.embedding_generated = False
            db.add(student)
            await db.commit()
            
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to delete photo {photo_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete photo: {str(e)}"
        )
        
    return

@router.post("/{id}/enroll", response_model=EnrollmentSummaryResponse)
async def enroll_student_faces(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Process all uploaded photos of the student, run quality checks,
    extract ArcFace embeddings, and index them to PostgreSQL and Qdrant.
    """
    logger.info(f"User {current_user.id} triggering face enrollment for student: {id}")
    
    # 1. Fetch student
    student_res = await db.execute(select(Student).filter(Student.id == id))
    student = student_res.scalars().first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {id} not found."
        )
        
    # 2. Fetch all student photos
    photos_res = await db.execute(select(StudentPhoto).filter(StudentPhoto.student_id == id))
    photos = photos_res.scalars().all()
    
    if not photos:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Student {id} has no uploaded photos. Please upload photos before enrollment."
        )
        
    # 3. Instantiate engines
    engine = FaceEnrollmentEngine()
    qdrant_store = QdrantVectorStore()
    
    logger.info(f"Starting enrollment for student_id: {id}")
    
    processed = 0
    successful = 0
    failed = 0
    quality_scores = {}
    errors = []
    
    for photo in photos:
        processed += 1
        
        # Check if embedding already exists for this photo
        emb_check = await db.execute(
            select(StudentFaceEmbedding).filter(StudentFaceEmbedding.photo_id == photo.id)
        )
        if emb_check.scalars().first():
            logger.info(f"Embedding already exists for photo {photo.id}. Skipping.")
            successful += 1
            continue
            
        # Process photo with quality gates
        res = engine.process_photo(photo.photo_path)
        if not res["success"]:
            failed += 1
            errors.append({"photo_id": str(photo.id), "filename": os.path.basename(photo.photo_path), "error": res["error"]})
            continue
            
        logger.info(f"Face detected in {photo.view} image")
        logger.info("ArcFace embedding generated dimension=512")
            
        # Duplicate checks
        try:
            qr = qdrant_store.client.query_points(
                collection_name=qdrant_store.face_collection_name,
                query=res["embedding"],
                limit=1,
                with_payload=True
            )
            closest = qr.points
            if closest and closest[0].score > 0.95:
                other_student_id = closest[0].payload.get("student_id")
                if other_student_id and other_student_id != str(id):
                    failed += 1
                    err_msg = f"Duplicate face embedding detected (similarity={closest[0].score:.3f} with student {other_student_id})."
                    errors.append({"photo_id": str(photo.id), "filename": os.path.basename(photo.photo_path), "error": err_msg})
                    continue
        except Exception as q_err:
            logger.warning(f"Failed to check duplicate embedding in Qdrant: {str(q_err)}")
            
        yaw, pitch, roll = res["pose"]
        embedding_id = uuid.uuid4()
        
        db_embedding = StudentFaceEmbedding(
            id=embedding_id,
            student_id=id,
            photo_id=photo.id,
            embedding=res["embedding"],
            model_version=engine.model_name,
            quality_score=res["quality_score"],
            blur_score=res["blur_score"],
            pose_yaw=yaw,
            pose_pitch=pitch,
            pose_roll=roll,
            face_bbox={
                "x1": res["bbox"][0],
                "y1": res["bbox"][1],
                "x2": res["bbox"][2],
                "y2": res["bbox"][3]
            }
        )
        db.add(db_embedding)
        logger.info(f"[ENROLLMENT AUDIT] Saved embedding to PostgreSQL: True (ID: {embedding_id})")
        
        # Save to Qdrant
        logger.info("Uploading embedding to student_face_embeddings")
        qdrant_store.upsert_face_embedding(
            embedding_id=embedding_id,
            vector=res["embedding"],
            payload={
                "student_id": id,
                "photo_id": photo.id,
                "view": photo.view,
                "quality": res["quality_score"],
                "department": student.department,
                "year": student.year
            }
        )
        logger.info(f"[ENROLLMENT AUDIT] Inserted embedding into Qdrant: True")
        logger.info(f"[ENROLLMENT AUDIT] Qdrant collection name: {qdrant_store.face_collection_name}")
        
        try:
            coll_info = qdrant_store.client.get_collection(qdrant_store.face_collection_name)
            logger.info(f"[ENROLLMENT AUDIT] Total vectors after insertion: {coll_info.points_count}")
        except Exception as e:
            logger.error(f"[ENROLLMENT AUDIT] Failed to query Qdrant collection points_count: {str(e)}")
        
        successful += 1
        quality_scores[photo.view] = res["quality_score"]
        
    await db.commit()
    
    # Update student status to note generated face embeddings
    if successful > 0:
        student.embedding_generated = True
        db.add(student)
        await db.commit()
    
    logger.info("Enrollment completed successfully")
    
    # Update face session status
    session_result = await db.execute(
        select(StudentFaceSession).filter(
            StudentFaceSession.student_id == id
        )
    )
    face_session = session_result.scalars().first()
    if face_session:
        face_session.status = "completed" if successful > 0 else "failed"
        await db.commit()
        
    return {
        "processed": processed,
        "successful": successful,
        "failed": failed,
        "quality_scores": quality_scores,
        "errors": errors
    }

@router.get("/{id}/enrollment-status", response_model=EnrollmentStatusResponse)
async def get_student_enrollment_status(
    id: uuid.UUID,
    db: AsyncSession = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user)
) -> Any:
    """
    Get enrollment details, missing views, and quality scores.
    """
    # 1. Fetch student
    student_res = await db.execute(select(Student).filter(Student.id == id))
    if not student_res.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Student with ID {id} not found."
        )
        
    # 2. Fetch photos
    photos_res = await db.execute(select(StudentPhoto).filter(StudentPhoto.student_id == id))
    photos = photos_res.scalars().all()
    
    # 3. Fetch face embeddings
    emb_res = await db.execute(select(StudentFaceEmbedding).filter(StudentFaceEmbedding.student_id == id))
    embeddings = emb_res.scalars().all()
    
    required_views = {"front", "left", "right", "up", "down", "masked", "glasses"}
    embedded_photos_map = {emb.photo_id: emb for emb in embeddings}
    successful_views = []
    quality_scores = {}
    
    for photo in photos:
        if photo.id in embedded_photos_map:
            successful_views.append(photo.view)
            quality_scores[photo.view] = embedded_photos_map[photo.id].quality_score
            
    missing_views = list(required_views - set(successful_views))
    
    return {
        "student_id": id,
        "photos_count": len(photos),
        "embeddings_count": len(embeddings),
        "missing_views": missing_views,
        "enrolled_views": list(set(successful_views)),
        "quality_scores": quality_scores
    }
