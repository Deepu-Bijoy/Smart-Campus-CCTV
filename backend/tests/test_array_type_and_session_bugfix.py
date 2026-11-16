import os
import sys
import uuid
import numpy as np
try:
    import pytest
    pytest_mark_async = pytest.mark.asyncio
except ImportError:
    def pytest_mark_async(f):
        return f
from sqlalchemy import select, text, Float
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.dialects.postgresql import asyncpg

# Add backend directory to sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import SqliteCompatibleArray, settings
from app.db.base_class import Base
from app.db.session import SessionLocal
from app.models.student import Student
from app.models.face_embedding import StudentFaceEmbedding
from app.models.track import PersonReid
from app.models.video import Video
from app.models.user import User
from app.services.targeted_verification import resolve_target_student
from app.api.v1.violence import get_violence_analysis_result

@pytest_mark_async
async def test_custom_type_compilation_all_dialects():
    """1. Custom type compilation against PostgreSQL (sync and asyncpg) and SQLite."""
    arr = SqliteCompatibleArray(Float)
    
    # Check item_type is properly set
    assert arr.item_type is not None
    
    pg_d = postgresql.dialect()
    asyncpg_d = asyncpg.dialect()
    sqlite_d = sqlite.dialect()
    
    pg_compiled = str(arr.compile(dialect=pg_d))
    asyncpg_compiled = str(arr.compile(dialect=asyncpg_d))
    sqlite_compiled = str(arr.compile(dialect=sqlite_d))
    
    assert "FLOAT[]" in pg_compiled
    assert "FLOAT[]" in asyncpg_compiled
    assert "JSON" in sqlite_compiled
    
    # Also verify no-argument initialization defaults safely
    arr_default = SqliteCompatibleArray()
    assert "FLOAT[]" in str(arr_default.compile(dialect=asyncpg_d))

@pytest_mark_async
async def test_embedding_select_query_execution():
    """2. Embedding SELECT query execution against active PostgreSQL database."""
    async with SessionLocal() as s:
        stmt = select(StudentFaceEmbedding).limit(1)
        res = await s.execute(stmt)
        record = res.scalars().first()
        if record:
            assert hasattr(record, "embedding")
            assert isinstance(record.embedding, list)
            assert len(record.embedding) == 512
            assert all(isinstance(x, (float, int)) for x in record.embedding[:5])

@pytest_mark_async
async def test_student_embedding_retrieval_and_parsing():
    """3. Student embedding retrieval and numeric validation."""
    async with SessionLocal() as s:
        # Fetch one student who has embeddings
        res = await s.execute(text("SELECT student_id FROM student_face_embeddings LIMIT 1"))
        sid = res.scalar()
        if sid:
            stmt = select(StudentFaceEmbedding).filter(StudentFaceEmbedding.student_id == sid)
            embs = (await s.execute(stmt)).scalars().all()
            assert len(embs) > 0
            for emb_rec in embs:
                raw_emb = emb_rec.embedding
                assert raw_emb is not None
                arr = np.array(raw_emb, dtype=np.float32)
                assert arr.shape == (512,)
                assert np.all(np.isfinite(arr))

@pytest_mark_async
async def test_resolve_target_student_valid_student():
    """4. resolve_target_student() with a valid student having embeddings."""
    async with SessionLocal() as s:
        # Find student with valid embeddings
        res = await s.execute(text("""
            SELECT s.name 
            FROM students s 
            JOIN student_face_embeddings sfe ON sfe.student_id = s.id 
            LIMIT 1
        """))
        st_name = res.scalar()
        assert st_name is not None
        
        result = await resolve_target_student(s, st_name)
        assert result["status"] == "RESOLVED_VALID_EMBEDDING"
        assert result["student"] is not None
        assert len(result["embeddings"]) > 0
        assert result["embeddings"][0].shape == (512,)
        # Check normalized L2 norm
        assert np.isclose(np.linalg.norm(result["embeddings"][0]), 1.0, atol=1e-5)

@pytest_mark_async
async def test_resolve_target_student_nonexistent_student():
    """5. resolve_target_student() when no student exists."""
    async with SessionLocal() as s:
        result = await resolve_target_student(s, "NonExistent_Student_Random_987654")
        assert result["status"] == "STUDENT_NOT_FOUND"
        assert result["student"] is None
        assert len(result["embeddings"]) == 0
        assert "not found" in result["error"].lower()

@pytest_mark_async
async def test_resolve_target_student_ash():
    """Verify resolve_target_student handles student 'Ash' without ARRAY.__init__ error."""
    async with SessionLocal() as s:
        result = await resolve_target_student(s, "Ash")
        # Ash exists in DB; verify resolve_target_student executes cleanly
        assert result["status"] in ["RESOLVED_VALID_EMBEDDING", "ENROLLMENT_MISSING_EMBEDDINGS"]
        if result["status"] == "ENROLLMENT_MISSING_EMBEDDINGS":
            assert result["student"].name == "Ash"

@pytest_mark_async
async def test_failure_status_persistence_after_exception():
    """6 & 7. Failure-status persistence after database exception with session rollback."""
    test_vid_id = uuid.uuid4()
    async with SessionLocal() as s:
        user_id = (await s.execute(text("SELECT id FROM users LIMIT 1"))).scalar()
        test_vid = Video(
            id=test_vid_id,
            filename=f"test_{test_vid_id.hex}.mp4",
            original_filename="test_err.mp4",
            file_path=f"storage/videos/test_{test_vid_id.hex}.mp4",
            status="processing",
            current_stage="Testing",
            progress_percentage=40,
            uploaded_by=user_id
        )
        s.add(test_vid)
        await s.commit()

    try:
        # Simulate an operation failure using an async session
        async with SessionLocal() as s:
            v_res = await s.execute(select(Video).filter(Video.id == test_vid_id))
            target_video = v_res.scalars().first()
            assert target_video is not None
            
            # Capture scalar identifier upfront
            target_vid_id = target_video.id
            
            # Intentionally cause a database error in this session
            try:
                # Trigger a bad query to break the session transaction
                await s.execute(text("SELECT * FROM non_existent_table_xyz_123"))
            except Exception as simulated_exc:
                # Rollback failed session
                await s.rollback()
                
                # Verify that accessing target_video attributes does NOT prevent independent persistence
                # Persist failed status using fresh independent session with scalar ID
                async with SessionLocal() as err_db:
                    ev_res = await err_db.execute(select(Video).filter(Video.id == target_vid_id))
                    err_video = ev_res.scalars().first()
                    assert err_video is not None
                    err_video.status = "failed"
                    err_video.current_stage = "Analysis Failed"
                    err_video.error_message = f"Violence detection failed: {str(simulated_exc)}"[:1024]
                    await err_db.commit()

        # Verify failed status was persisted cleanly
        async with SessionLocal() as check_db:
            chk = (await check_db.execute(select(Video).filter(Video.id == test_vid_id))).scalars().first()
            assert chk is not None
            assert chk.status == "failed"
            assert chk.current_stage == "Analysis Failed"
            assert "non_existent_table" in (chk.error_message or "")
    finally:
        # Clean up temporary test video record
        async with SessionLocal() as cleanup_db:
            await cleanup_db.execute(text("DELETE FROM videos WHERE id = :vid").bindparams(vid=test_vid_id))
            await cleanup_db.commit()

@pytest_mark_async
async def test_get_violence_analysis_result_endpoint_regression():
    """8. Existing violence-analysis endpoint regression."""
    async with SessionLocal() as s:
        # Find an existing video with completed violence analysis
        res = await s.execute(text("""
            SELECT id FROM videos 
            WHERE status = 'completed' AND current_stage ILIKE '%violence%' 
            ORDER BY created_at DESC LIMIT 1
        """))
        vid = res.scalar()
        if not vid:
            # Fallback to any completed video
            res = await s.execute(text("SELECT id FROM videos WHERE status = 'completed' LIMIT 1"))
            vid = res.scalar()

        if vid:
            admin_user = User(id=uuid.uuid4(), role="admin")
            response = await get_violence_analysis_result(video_id=vid, db=s, current_user=admin_user)
            assert response is not None
            assert hasattr(response, "video_id")
            assert hasattr(response, "status")
            assert hasattr(response, "verdict")
            assert hasattr(response, "segments")
            assert hasattr(response, "targeted_verification")
            assert response.targeted_verification is not None
            assert hasattr(response.targeted_verification, "ash")
            assert hasattr(response.targeted_verification, "jose_john")
