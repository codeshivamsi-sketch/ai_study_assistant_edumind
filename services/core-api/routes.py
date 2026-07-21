from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Any, Optional
import uuid

from database import get_db
from identity import get_current_user
from models import User, Document, Quiz, QuizAttempt
from logger import log
from worker import celery_app
from agentic_client import upload_document

router = APIRouter()

# ---- Documents ----

class DocumentCreateRequest(BaseModel):
    title: str
    status: str = "uploaded"

class DocumentUpdateRequest(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None

async def _get_owned_document(document_id: uuid.UUID, user: User, db: AsyncSession) -> Document:
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.user_id == user.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document

@router.post("/documents")
async def create_document(
    request: DocumentCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = Document(user_id=user.id, title=request.title, status=request.status)
    db.add(document)
    await db.commit()
    await db.refresh(document)
    log.info("document_created", document_id=str(document.id), user_id=str(user.id))
    return document

@router.get("/documents")
async def list_documents(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(select(Document).where(Document.user_id == user.id))
    return result.scalars().all()

@router.get("/documents/{document_id}")
async def get_document(
    document_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await _get_owned_document(document_id, user, db)

@router.patch("/documents/{document_id}")
async def update_document(
    document_id: uuid.UUID,
    request: DocumentUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = await _get_owned_document(document_id, user, db)
    if request.title is not None:
        document.title = request.title
    if request.status is not None:
        document.status = request.status
    await db.commit()
    await db.refresh(document)
    return document

@router.delete("/documents/{document_id}")
async def delete_document(
    document_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    document = await _get_owned_document(document_id, user, db)
    await db.delete(document)
    await db.commit()
    return {"deleted": True}

@router.post("/documents/{document_id}/upload")
async def upload_document_file(
    document_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = await _get_owned_document(document_id, user, db)
    content = await file.read()
    document.status = "processing"
    await db.commit()
    try:
        await upload_document(str(document_id), file.filename, content)
    except Exception as e:
        document.status = "failed"
        await db.commit()
        log.warning("document_upload_failed", document_id=str(document_id), error=str(e))
        raise HTTPException(status_code=502, detail="Document ingestion failed")
    document.status = "ready"
    await db.commit()
    await db.refresh(document)
    log.info("document_uploaded", document_id=str(document_id))
    return document

# ---- Quizzes ----

class QuizCreateRequest(BaseModel):
    document_id: uuid.UUID
    topic: str
    questions: Any

class QuizUpdateRequest(BaseModel):
    topic: Optional[str] = None
    questions: Optional[Any] = None

class GenerateQuizRequest(BaseModel):
    document_id: uuid.UUID
    topic: str

async def _get_owned_quiz(quiz_id: uuid.UUID, user: User, db: AsyncSession) -> Quiz:
    result = await db.execute(
        select(Quiz)
        .join(Document, Quiz.document_id == Document.id)
        .where(Quiz.id == quiz_id, Document.user_id == user.id)
    )
    quiz = result.scalar_one_or_none()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz

@router.post("/quizzes")
async def create_quiz(
    request: QuizCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_owned_document(request.document_id, user, db)
    quiz = Quiz(document_id=request.document_id, topic=request.topic, questions=request.questions)
    db.add(quiz)
    await db.commit()
    await db.refresh(quiz)
    try:
        celery_app.send_task("notify_quiz_ready", args=[str(user.id), str(quiz.id)])
    except Exception as e:
        log.warning("notify_quiz_ready_dispatch_failed", quiz_id=str(quiz.id), error=str(e))
    return quiz

@router.post("/quizzes/generate", status_code=202)
async def generate_quiz_request(
    request: GenerateQuizRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = await _get_owned_document(request.document_id, user, db)
    if document.status != "ready":
        raise HTTPException(status_code=409, detail="Document not ready for quiz generation")
    task = celery_app.send_task(
        "generate_quiz",
        args=[str(user.id), str(request.document_id), request.topic],
    )
    return {"job_id": task.id}

@router.get("/quizzes")
async def list_quizzes(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(
        select(Quiz).join(Document, Quiz.document_id == Document.id).where(Document.user_id == user.id)
    )
    return result.scalars().all()

@router.get("/quizzes/{quiz_id}")
async def get_quiz(quiz_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await _get_owned_quiz(quiz_id, user, db)

@router.patch("/quizzes/{quiz_id}")
async def update_quiz(
    quiz_id: uuid.UUID,
    request: QuizUpdateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    quiz = await _get_owned_quiz(quiz_id, user, db)
    if request.topic is not None:
        quiz.topic = request.topic
    if request.questions is not None:
        quiz.questions = request.questions
    await db.commit()
    await db.refresh(quiz)
    return quiz

@router.delete("/quizzes/{quiz_id}")
async def delete_quiz(
    quiz_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    quiz = await _get_owned_quiz(quiz_id, user, db)
    await db.delete(quiz)
    await db.commit()
    return {"deleted": True}

# ---- Quiz attempts ----

class QuizAttemptCreateRequest(BaseModel):
    quiz_id: uuid.UUID
    answers: Any
    score: float

@router.post("/quiz_attempts")
async def create_quiz_attempt(
    request: QuizAttemptCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_owned_quiz(request.quiz_id, user, db)
    attempt = QuizAttempt(
        quiz_id=request.quiz_id, user_id=user.id, answers=request.answers, score=request.score
    )
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    return attempt

@router.get("/quizzes/{quiz_id}/stats")
async def get_quiz_stats(
    quiz_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await _get_owned_quiz(quiz_id, user, db)
    result = await db.execute(
        select(func.avg(QuizAttempt.score), func.count(QuizAttempt.id)).where(QuizAttempt.quiz_id == quiz_id)
    )
    avg_score, attempt_count = result.one()
    return {
        "avg_score": float(avg_score) if avg_score is not None else None,
        "attempt_count": attempt_count,
    }
