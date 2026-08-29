import logging
from celery import Celery
from celery.signals import setup_logging
from app.core.config import settings

import os
broker_url = settings.CELERY_BROKER_URL
result_backend = settings.CELERY_RESULT_BACKEND
 
if settings.CELERY_ALWAYS_EAGER:
    broker_url = "memory://"
    result_backend = "cache+memory://"
 
celery_app = Celery(
    "tasks",
    broker=broker_url,
    backend=result_backend,
)
celery_app.set_default()

celery_app.conf.update(
    task_always_eager=settings.CELERY_ALWAYS_EAGER,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.tasks.video_tasks.process_video": {"queue": "gpu_queue"},
        "app.tasks.cpu_tasks.*": {"queue": "cpu_queue"},
    },
)
print("CELERY ALWAYS EAGER CONFIGURED TO:", celery_app.conf.task_always_eager)

@setup_logging.connect
def config_loggers(*args, **kw):
    from logging.config import dictConfig
    dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "[%(asctime)s][%(levelname)s][%(name)s] %(message)s",
            }
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            }
        },
        "root": {
            "handlers": ["console"],
            "level": settings.LOG_LEVEL,
        }
    })

# Import tasks module to register video, CPU, and bulk tasks
import app.tasks.video_tasks
import app.tasks.cpu_tasks
import app.tasks.bulk_tasks
