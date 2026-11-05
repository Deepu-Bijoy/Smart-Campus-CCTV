import asyncio
import uuid
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import atexit
try:
    from celery import shared_task, Task
except ImportError:
    def shared_task(*args, **kwargs):
        def decorator(func):
            return func
        return decorator
    class Task:
        pass

from sqlalchemy.future import select

from app.db.session import SessionLocal
from app.models.video import Video
from app.pipeline.orchestrator import VideoProcessingOrchestrator

logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=1)
_background_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video_proc_")
atexit.register(lambda: _background_executor.shutdown(wait=False))

_active_processing_video_ids: set[str] = set()
_cancelled_video_ids: set[str] = set()
_video_to_task_id: dict[str, str] = {}

class VideoProcessingCancelledException(Exception):
    """Raised when a video task is cancelled/deleted during active processing."""
    pass

def register_video_task(video_id: str | uuid.UUID, task_id: str) -> None:
    """Associate a video ID with its Celery task ID for cancellation tracking."""
    _video_to_task_id[str(video_id)] = str(task_id)

def is_video_actively_processing(video_id: str | uuid.UUID) -> bool:
    """Return True if a video task is genuinely executing in the background executor or worker."""
    return str(video_id) in _active_processing_video_ids

def is_video_cancelled(video_id: str | uuid.UUID) -> bool:
    """Return True if the video processing has been cancelled or deleted."""
    return str(video_id) in _cancelled_video_ids

def cancel_video_processing(video_id: str | uuid.UUID) -> None:
    """
    Cancel active or queued processing for a video.
    Revokes the Celery task where possible and marks the ID as cancelled so workers abort.
    """
    vid_str = str(video_id)
    _cancelled_video_ids.add(vid_str)
    _active_processing_video_ids.discard(vid_str)
    task_id = _video_to_task_id.pop(vid_str, None)
    if task_id:
        try:
            from app.tasks.cel_app import celery_app
            celery_app.control.revoke(task_id, terminate=True, signal="SIGTERM")
            logger.info(f"Revoked Celery task {task_id} for video {vid_str}")
        except Exception as e:
            logger.warning(f"Could not revoke Celery task {task_id} for video {vid_str}: {e}")

class BackgroundEagerTask(Task):
    """
    Custom Celery Task class that prevents eager Celery execution
    from blocking the HTTP upload request. When task_always_eager is enabled,
    dispatches through apply_async / delay submit work to a dedicated background
    executor rather than executing synchronously on the calling HTTP thread.
    Direct .apply(...) calls continue to execute synchronously for deterministic testing.
    """
    def apply_async(self, args=None, kwargs=None, **options):
        from app.core.config import settings
        is_eager = (
            getattr(settings, "CELERY_ALWAYS_EAGER", False)
            or bool(getattr(getattr(self, "app", None), "conf", None) and getattr(self.app.conf, "task_always_eager", False))
        )
        if is_eager:
            kwargs = dict(kwargs or {})
            kwargs["_is_async_delay"] = True
            return self.apply(args=args, kwargs=kwargs, **options)
        return super().apply_async(args=args, kwargs=kwargs, **options)

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
    if is_video_cancelled(video_id):
        logger.info(f"Video {video_id} is marked cancelled/deleted. Skipping progress update to '{stage}'.")
        return

    async with SessionLocal() as db:
        result = await db.execute(select(Video).filter(Video.id == video_id))
        video = result.scalars().first()
        if not video:
            logger.info(f"Video {video_id} no longer exists in DB. Skipping progress update.")
            return

        video.status = status
        if stage is not None:
            video.current_stage = stage

        # Monotonic progress within a single processing run:
        if status == "failed":
            # On failure, preserve the actual progress percentage achieved (never fake 100%)
            if 0 < progress < 100:
                video.progress_percentage = max(video.progress_percentage or 0, progress)
        elif stage in ["Initialization", "Queued", "Retrying"]:
            video.progress_percentage = progress
        else:
            video.progress_percentage = max(video.progress_percentage or 0, progress)

        # Do not display 100% until processing genuinely completes
        if status != "completed" and video.progress_percentage >= 100:
            video.progress_percentage = 99

        if started_at:
            video.processing_started_at = started_at
        if finished_at:
            video.processing_finished_at = finished_at
        if error_message is not None:
            video.error_message = error_message

        await db.commit()

@shared_task(
    bind=True,
    base=BackgroundEagerTask,
    max_retries=3,
    default_retry_delay=60,
)
def process_video(self, video_id_str: str, _is_async_delay: bool = False) -> None:
    def _execute():
        if is_video_cancelled(video_id_str):
            logger.info(f"Celery task for video {video_id_str} skipped before execution: video already cancelled/deleted.")
            return

        if getattr(self, "request", None) and getattr(self.request, "id", None):
            register_video_task(video_id_str, self.request.id)

        logger.info(f"Celery worker received video task for ID: {video_id_str}")
        _active_processing_video_ids.add(video_id_str)
        try:
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
                if is_video_cancelled(video_id_str):
                    logger.info(f"Video {video_id_str} was cancelled during stage '{stage}'. Halting execution.")
                    raise VideoProcessingCancelledException(f"Task for video {video_id_str} cancelled during {stage}.")

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
            except VideoProcessingCancelledException:
                logger.info(f"Pipeline execution for video {video_id_str} aborted cleanly due to cancellation/deletion.")
                return
            except Exception as exc:
                if is_video_cancelled(video_id_str):
                    logger.info(f"Suppressed worker error for deleted/cancelled video {video_id_str}: {exc}")
                    return

                logger.error(f"Error processing video {video_id_str}: {type(exc).__name__}: {str(exc)}")

                # Permanent errors: missing files, bad values, or missing Python packages.
                is_permanent_error = isinstance(exc, (
                    FileNotFoundError,
                    ValueError,
                    ModuleNotFoundError,
                    ImportError,
                ))

                retries = getattr(getattr(self, "request", None), "retries", 0) or 0
                if not is_permanent_error and retries < self.max_retries and not _is_async_delay:
                    run_sync(_update_video_progress(
                        video_id=video_id,
                        status="queued",
                        stage="Retrying",
                        progress=0,
                        error_message=f"Transient failure. Retrying task. Error: {str(exc)}"
                    ))
                    logger.info(f"Retrying task for video {video_id_str} (attempt {retries + 1}/{self.max_retries})")
                    raise self.retry(exc=exc)
                else:
                    run_sync(_update_video_progress(
                        video_id=video_id,
                        status="failed",
                        stage="Failed",
                        progress=0,
                        finished_at=datetime.now(timezone.utc),
                        error_message=f"Processing failed: {str(exc)}"
                    ))
        finally:
            _active_processing_video_ids.discard(video_id_str)

    if _is_async_delay:
        logger.info(f"Eager mode: Submitting video task {video_id_str} to background executor.")
        _background_executor.submit(_execute)
        return None
    else:
        return _execute()
