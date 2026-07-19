from celery import Celery
from grpc_client import notify_quiz_ready as send_grpc_notification
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RETRY_COUNTDOWN = int(os.getenv("NOTIFY_QUIZ_READY_RETRY_COUNTDOWN", "60"))

celery_app = Celery(
    "core-api",
    broker=REDIS_URL,
    backend=REDIS_URL
)


@celery_app.task(bind=True, max_retries=3, name="notify_quiz_ready")
def notify_quiz_ready(self, user_id, quiz_id):
    try:
        send_grpc_notification(user_id, quiz_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=RETRY_COUNTDOWN)
