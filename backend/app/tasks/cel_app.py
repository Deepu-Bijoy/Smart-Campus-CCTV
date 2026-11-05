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
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    task_routes={
        "app.tasks.video_tasks.process_video": {"queue": "gpu_queue"},
        "app.tasks.bulk_tasks.bulk_enroll_faces_task": {"queue": "gpu_queue"},
        "app.tasks.cpu_tasks.*": {"queue": "cpu_queue"},
    },
)
print(f"CELERY CONFIG: broker={broker_url}, always_eager={celery_app.conf.task_always_eager}")

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

import time
from typing import Dict, Any

_worker_status_cache: Dict[str, Any] = {"timestamp": 0.0, "data": {}}

def get_celery_worker_status(timeout: float = 0.5) -> Dict[str, Any]:
    """
    Check if Celery workers are active and which queues are being consumed.
    Uses a 5-second TTL cache to prevent connection overhead on repeated API calls.
    """
    global _worker_status_cache
    now = time.time()
    if now - _worker_status_cache["timestamp"] < 5.0 and _worker_status_cache["data"]:
        return _worker_status_cache["data"]

    if celery_app.conf.task_always_eager:
        res = {
            "online": True,
            "eager": True,
            "workers": ["local_eager"],
            "active_queues": ["gpu_queue", "cpu_queue"],
            "error": None
        }
        _worker_status_cache = {"timestamp": now, "data": res}
        return res

    try:
        insp = celery_app.control.inspect(timeout=timeout)
        ping_res = insp.ping() if insp else None
        if ping_res:
            workers = list(ping_res.keys())
            active_q = insp.active_queues() or {}
            all_queues = []
            for w, q_list in active_q.items():
                for q in q_list:
                    if isinstance(q, dict) and "name" in q:
                        all_queues.append(q["name"])
            res = {
                "online": True,
                "eager": False,
                "workers": workers,
                "active_queues": list(set(all_queues)),
                "error": None
            }
        else:
            res = {
                "online": False,
                "eager": False,
                "workers": [],
                "active_queues": [],
                "error": "No active Celery workers responding to ping on broker."
            }
    except Exception as e:
        res = {
            "online": False,
            "eager": False,
            "workers": [],
            "active_queues": [],
            "error": str(e)
        }

    _worker_status_cache = {"timestamp": now, "data": res}
    return res
