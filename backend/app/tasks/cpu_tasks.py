import logging
from celery import shared_task

logger = logging.getLogger(__name__)

@shared_task
def compile_report_pdf_task(report_id: str) -> None:
    logger.info(f"Compiling report PDF for report ID: {report_id} on CPU worker")

@shared_task
def dispatch_notifications_task(event_id: str) -> None:
    logger.info(f"Dispatching notifications for event ID: {event_id} on CPU worker")

@shared_task
def update_timeline_task(student_id: str) -> None:
    logger.info(f"Updating timeline for student ID: {student_id} on CPU worker")
