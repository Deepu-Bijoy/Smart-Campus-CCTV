import asyncio
import uuid
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from celery import shared_task
from sqlalchemy.future import select

from app.db.session import SessionLocal
from app.models.video import Video
from app.pipeline.orchestrator import VideoProcessingOrchestrator

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1)

def run_sync(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return _executor.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)

async def _update_video_progress(
    video_id: uuid.UUID,
    status: str,
    stage: str = None,
    progress: int = 0,
    started_at: datetime = None,
    finished_at: datetime = None,
    error_message: str = None
) -> None:
    async with SessionLocal() as db:
        result = await db.execute(select(Video).filter(Video.id == video_id))
        video = result.scalars().first()
        if not video:
            logger.error(f"Cannot update progress: Video {video_id} not found in DB.")
            return

        video.status = status
        if stage is not None:
            video.current_stage = stage
        video.progress_percentage = progress
        if started_at:
            video.processing_started_at = started_at
        if finished_at:
            video.processing_finished_at = finished_at
        if error_message is not None:
            video.error_message = error_message

        await db.commit()

@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def process_video(self, video_id_str: str) -> None:
    logger.info(f"Celery worker received video task for ID: {video_id_str}")
    video_id = uuid.UUID(video_id_str)
    
    now_utc = datetime.now(timezone.utc)
    run_sync(_update_video_progress(
        video_id=video_id,
        status="processing",
        stage="Initialization",
        progress=0,
        started_at=now_utc
    ))
    
    async def progress_callback(stage: str, percentage: int) -> None:
        if stage == "Completed":
            await _update_video_progress(
                video_id=video_id,
                status="completed",
                stage=stage,
                progress=percentage,
                finished_at=datetime.now(timezone.utc)
            )
        else:
            await _update_video_progress(
                video_id=video_id,
                status="processing",
                stage=stage,
                progress=percentage
            )

    async def run_orchestration():
        async with SessionLocal() as db:
            orchestrator = VideoProcessingOrchestrator(db, progress_callback)
            await orchestrator.execute(video_id)

    try:
        run_sync(run_orchestration())
    except Exception as exc:
        logger.error(f"Error processing video {video_id_str}: {type(exc).__name__}: {str(exc)}")

        # Permanent errors: missing files, bad values, or missing Python packages.
        # Missing packages should NEVER trigger a retry — they will fail every time.
        is_permanent_error = isinstance(exc, (
            FileNotFoundError,
            ValueError,
            ModuleNotFoundError,  # Missing pip package — never retry
            ImportError,           # Missing pip package — never retry
        ))

        if not is_permanent_error and self.request.retries < self.max_retries:
            run_sync(_update_video_progress(
                video_id=video_id,
                status="queued",
                stage="Retrying",
                progress=0,
                error_message=f"Transient failure. Retrying task. Error: {str(exc)}"
            ))
            logger.info(f"Retrying task for video {video_id_str} (attempt {self.request.retries + 1}/{self.max_retries})")
            raise self.retry(exc=exc)
        else:
            run_sync(_update_video_progress(
                video_id=video_id,
                status="failed",
                stage="Failed",
                progress=100,
                finished_at=datetime.now(timezone.utc),
                error_message=f"Processing failed: {str(exc)}"
            ))
