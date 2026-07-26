import asyncio
import os

from celery import Celery
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from agentic_client import request_quiz
from database import DATABASE_URL
from grpc_client import notify_quiz_ready as send_grpc_notification
from logger import log
from models import Document, Quiz

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RETRY_COUNTDOWN = int(os.getenv("NOTIFY_QUIZ_READY_RETRY_COUNTDOWN", "60"))
GENERATE_QUIZ_RETRY_COUNTDOWN = int(os.getenv("GENERATE_QUIZ_RETRY_COUNTDOWN", "30"))

celery_app = Celery(
    "core-api",
    broker=REDIS_URL,
    backend=REDIS_URL
)


@celery_app.task(bind=True, max_retries=3, name="notify_quiz_ready")
def notify_quiz_ready(self, user_id, quiz_id=None, chat_id=None, message_id=None):
    try:
        send_grpc_notification(user_id, quiz_id=quiz_id, chat_id=chat_id, message_id=message_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=RETRY_COUNTDOWN)


async def _insert_quiz(document_id: str, topic: str, questions: list) -> str:
    # A fresh engine per call, not database.py's shared AsyncSessionLocal:
    # asyncio.run() (see generate_quiz below) gives this coroutine a
    # brand-new event loop every invocation, but the shared engine's
    # asyncpg connection pool binds connections to whichever loop created
    # them -- reusing it across separate asyncio.run() calls raises
    # "attached to a different loop"/"another operation is in progress".
    # Creating and disposing the engine within this one call's own loop
    # sidesteps that entirely.
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with SessionLocal() as session:
            quiz = Quiz(document_id=document_id, topic=topic, questions=questions)
            session.add(quiz)
            await session.commit()
            await session.refresh(quiz)
            return str(quiz.id)
    finally:
        await engine.dispose()


async def _mark_document_failed(document_id: str) -> None:
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with SessionLocal() as session:
            document = await session.get(Document, document_id)
            if document:
                document.status = "failed"
                await session.commit()
    finally:
        await engine.dispose()


@celery_app.task(bind=True, max_retries=2, name="generate_quiz")
def generate_quiz(self, user_id, document_id, topic):
    try:
        questions = request_quiz(document_id, topic)
    except Exception as exc:
        if self.request.retries >= self.max_retries:
            asyncio.run(_mark_document_failed(document_id))
        raise self.retry(exc=exc, countdown=GENERATE_QUIZ_RETRY_COUNTDOWN)

    try:
        quiz_id = asyncio.run(_insert_quiz(document_id, topic, questions))
    except Exception as exc:
        log.error("generate_quiz_insert_failed", document_id=document_id, error=str(exc))
        asyncio.run(_mark_document_failed(document_id))
        return

    try:
        celery_app.send_task("notify_quiz_ready", args=[user_id, quiz_id])
    except Exception as exc:
        log.warning("notify_quiz_ready_dispatch_failed", quiz_id=quiz_id, error=str(exc))
