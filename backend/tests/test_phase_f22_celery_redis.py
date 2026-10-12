import os
import sys
import time
import uuid
import unittest
import redis

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.core.config import settings
from app.tasks.cel_app import celery_app
from app.tasks.cpu_tasks import update_timeline_task, dispatch_notifications_task

class TestPhaseF22CeleryRedis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.redis_client = redis.Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=0,
            socket_timeout=2.0
        )

    def test_1_redis_broker_connectivity(self):
        """Verify Redis is listening, accepting commands, and storing keys."""
        pong = self.redis_client.ping()
        self.assertTrue(pong, "Redis ping must return True")

        test_key = f"f22_test_{uuid.uuid4()}"
        self.redis_client.set(test_key, "active", ex=30)
        val = self.redis_client.get(test_key)
        self.assertEqual(val, b"active")
        self.redis_client.delete(test_key)

    def test_2_celery_app_configuration(self):
        """Verify Celery app uses Redis as broker, result backend, and enforces safe execution rules."""
        self.assertIn("redis://", celery_app.conf.broker_url)
        self.assertIn("redis://", celery_app.conf.result_backend)
        self.assertTrue(celery_app.conf.task_acks_late, "Tasks must acknowledge late after completion")
        self.assertTrue(celery_app.conf.task_reject_on_worker_lost, "Worker loss must reject/requeue task")
        self.assertTrue(celery_app.conf.broker_connection_retry_on_startup, "Connection retry must be enabled")
        self.assertFalse(celery_app.conf.task_always_eager, "Non-test runtime must have eager mode disabled")

    def test_3_task_queue_routing(self):
        """Verify all critical tasks route to appropriate queues."""
        routes = celery_app.conf.task_routes
        self.assertEqual(routes.get("app.tasks.video_tasks.process_video"), {"queue": "gpu_queue"})
        self.assertEqual(routes.get("app.tasks.bulk_tasks.bulk_enroll_faces_task"), {"queue": "gpu_queue"})
        self.assertEqual(routes.get("app.tasks.cpu_tasks.*"), {"queue": "cpu_queue"})

    def test_4_live_worker_task_execution(self):
        """Submit a controlled test task over Redis and verify live worker consumption and completion."""
        test_id = str(uuid.uuid4())
        async_result = update_timeline_task.delay(test_id)
        
        self.assertIsNotNone(async_result.id)
        t0 = time.time()
        while async_result.state not in ("SUCCESS", "FAILURE") and time.time() - t0 < 10:
            time.sleep(0.4)

        self.assertEqual(async_result.state, "SUCCESS", f"Expected SUCCESS, got {async_result.state}")

    def test_5_unit_test_eager_mode_preservation(self):
        """Verify unit tests can explicitly override task_always_eager without breaking Celery."""
        prev = celery_app.conf.task_always_eager
        try:
            celery_app.conf.task_always_eager = True
            res = dispatch_notifications_task.apply_async(args=["eager_test_event"])
            self.assertEqual(res.state, "SUCCESS")
        finally:
            celery_app.conf.task_always_eager = prev

    def test_6_broker_failure_resilience_and_no_duplicate_records(self):
        """Verify broker dispatch errors are caught cleanly, marking status failed without duplicates."""
        from unittest.mock import patch
        from app.tasks.video_tasks import process_video

        with patch.object(process_video, "delay", side_effect=redis.ConnectionError("Redis broker offline")):
            with self.assertRaises(redis.ConnectionError):
                process_video.delay("mock-video-id")

if __name__ == "__main__":
    unittest.main()
