import os
import uuid
import time
import logging
from datetime import datetime, timezone
from celery import shared_task
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.bulk_import import BulkImportJob
from app.models.student import Student, StudentPhoto, StudentFaceSession
from app.models.face_embedding import StudentFaceEmbedding
from app.pipeline.face_engine import FaceEnrollmentEngine
from app.services.vector_store import QdrantVectorStore

logger = logging.getLogger(__name__)

@shared_task(bind=True, queue="gpu_queue")
def bulk_enroll_faces_task(self, job_id_str: str) -> None:
    logger.info(f"Starting bulk face enrollment task for Job: {job_id_str}")
    job_id = uuid.UUID(job_id_str)
    
    engine = FaceEnrollmentEngine()
    qdrant_store = QdrantVectorStore()
    
    async def process_job():
        async with SessionLocal() as db:
            result = await db.execute(select(BulkImportJob).filter(BulkImportJob.id == job_id))
            job = result.scalars().first()
            if not job:
                logger.error(f"Bulk Import Job {job_id} not found in DB.")
                return
                
            job.status = "processing"
            await db.commit()
            
            stmt = select(Student).filter(Student.status == "active")
            student_res = await db.execute(stmt)
            students = student_res.scalars().all()
            
            students_to_process = []
            for s in students:
                p_res = await db.execute(select(StudentPhoto).filter(StudentPhoto.student_id == s.id))
                photos = p_res.scalars().all()
                if not photos:
                    continue
                emb_res = await db.execute(select(StudentFaceEmbedding).filter(StudentFaceEmbedding.student_id == s.id))
                embs = emb_res.scalars().all()
                if len(embs) < len(photos):
                    students_to_process.append((s, photos))
                    
            if not students_to_process:
                job.status = "completed"
                job.report = {
                    "summary": "No pending face photo enrollments found.",
                    "successful": 0,
                    "failed": 0,
                    "errors": []
                }
                await db.commit()
                return

            job.total_records = len(students_to_process)
            await db.commit()

            successful = 0
            failed = 0
            errors_log = []
            
            start_time = time.time()
            
            for idx, (student, photos) in enumerate(students_to_process):
                db.expire(job)
                fresh_job_res = await db.execute(select(BulkImportJob).filter(BulkImportJob.id == job_id))
                job = fresh_job_res.scalars().first()
                if job.status == "cancelled":
                    logger.info(f"Bulk Import Job {job_id} cancelled by operator.")
                    return
                    
                job.current_roll_number = student.university_roll_number
                await db.commit()
                
                student_success = False
                student_failed_reasons = []
                
                for photo in photos:
                    emb_check = await db.execute(
                        select(StudentFaceEmbedding).filter(StudentFaceEmbedding.photo_id == photo.id)
                    )
                    if emb_check.scalars().first():
                        student_success = True
                        continue
                        
                    res = engine.process_photo(photo.photo_path)
                    if not res["success"]:
                        student_failed_reasons.append({
                            "photo_id": str(photo.id),
                            "filename": os.path.basename(photo.photo_path),
                            "error": res["error"]
                        })
                        continue

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
                            if other_student_id and other_student_id != str(student.id):
                                err_msg = f"Duplicate face embedding matched with student {other_student_id}."
                                student_failed_reasons.append({
                                    "photo_id": str(photo.id),
                                    "filename": os.path.basename(photo.photo_path),
                                    "error": err_msg
                                })
                                continue
                    except Exception as q_err:
                        logger.warning(f"Qdrant duplicate check failed: {str(q_err)}")

                    embedding_id = uuid.uuid4()
                    db_embedding = StudentFaceEmbedding(
                        id=embedding_id,
                        student_id=student.id,
                        photo_id=photo.id,
                        embedding=res["embedding"],
                        model_version=engine.model_name,
                        quality_score=res["quality_score"],
                        blur_score=res["blur_score"],
                        pose_yaw=res["pose"][0],
                        pose_pitch=res["pose"][1],
                        pose_roll=res["pose"][2],
                        face_bbox={
                            "x1": res["bbox"][0],
                            "y1": res["bbox"][1],
                            "x2": res["bbox"][2],
                            "y2": res["bbox"][3]
                        }
                    )
                    db.add(db_embedding)
                    logger.info(f"[ENROLLMENT AUDIT] Saved embedding to PostgreSQL: True (ID: {embedding_id})")

                    qdrant_store.upsert_face_embedding(
                        embedding_id=embedding_id,
                        vector=res["embedding"],
                        payload={
                            "student_id": student.id,
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
                    
                    student_success = True
                    
                if student_success:
                    successful += 1
                else:
                    failed += 1
                    errors_log.append({
                        "student_id": str(student.id),
                        "roll_number": student.university_roll_number,
                        "name": student.name,
                        "failures": student_failed_reasons
                    })

                elapsed = time.time() - start_time
                avg_time_per_student = elapsed / (idx + 1)
                remaining_students = len(students_to_process) - (idx + 1)
                eta = remaining_students * avg_time_per_student
                
                job.processed_records = idx + 1
                job.successful_records = successful
                job.failed_records = failed
                job.estimated_remaining_seconds = eta
                await db.commit()

            job.status = "completed"
            job.estimated_remaining_seconds = 0.0
            job.report = {
                "summary": "Bulk enrollment completed.",
                "total": len(students_to_process),
                "successful": successful,
                "failed": failed,
                "errors": errors_log
            }
            await db.commit()

    import asyncio
    try:
        loop = asyncio.get_running_loop()
        import nest_asyncio
        nest_asyncio.apply()
        loop.run_until_complete(process_job())
    except RuntimeError:
        asyncio.run(process_job())
