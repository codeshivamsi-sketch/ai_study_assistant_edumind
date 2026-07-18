from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Any, Optional
import asyncio
import uuid

from database import get_db
from identity import get_current_user
from models import User, Document, Quiz, QuizAttempt
from logger import log
import grpc
from grpc_client import notify_quiz_ready

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

# ---- Quizzes ----

class QuizCreateRequest(BaseModel):
    document_id: uuid.UUID
    topic: str
    questions: Any

class QuizUpdateRequest(BaseModel):
    topic: Optional[str] = None
    questions: Optional[Any] = None

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
        await asyncio.to_thread(notify_quiz_ready, str(user.id), str(quiz.id))
    except grpc.RpcError as e:
        log.warning("notify_quiz_ready_failed", quiz_id=str(quiz.id), error=str(e))
    return quiz

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
