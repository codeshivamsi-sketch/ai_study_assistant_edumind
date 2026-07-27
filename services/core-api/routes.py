from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Any, Optional
import json
import os
import uuid

from database import get_db
from identity import get_current_user
from models import User, Document, Quiz, QuizAttempt, Chat, Message
from logger import log
from worker import celery_app
from agentic_client import upload_document, request_answer, request_evaluation

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

# ---- Chats ----

class ChatCreateRequest(BaseModel):
    document_id: uuid.UUID
    title: Optional[str] = None

class MessageCreateRequest(BaseModel):
    content: str
    intent: Optional[str] = None
    quiz_id: Optional[uuid.UUID] = None

async def _get_owned_chat(chat_id: uuid.UUID, user: User, db: AsyncSession) -> Chat:
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id)
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat

@router.post("/chats")
async def create_chat(
    request: ChatCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = await _get_owned_document(request.document_id, user, db)
    if document.status != "ready":
        raise HTTPException(status_code=409, detail="Document not ready for chat")
    chat = Chat(user_id=user.id, document_id=request.document_id, title=request.title)
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    log.info("chat_created", chat_id=str(chat.id), document_id=str(document.id), user_id=str(user.id))
    return chat

@router.get("/chats")
async def list_chats(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(
        select(Chat).where(Chat.user_id == user.id).order_by(Chat.created_at.desc())
    )
    return result.scalars().all()

@router.get("/chats/{chat_id}")
async def get_chat(
    chat_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await _get_owned_chat(chat_id, user, db)

@router.get("/chats/{chat_id}/messages")
async def list_messages(
    chat_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await _get_owned_chat(chat_id, user, db)
    result = await db.execute(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.asc())
    )
    return result.scalars().all()

@router.post("/chats/{chat_id}/messages", status_code=202)
async def create_message(
    chat_id: uuid.UUID,
    request: MessageCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    chat = await _get_owned_chat(chat_id, user, db)

    quiz = None
    if request.intent == "quiz_answer":
        if request.quiz_id is None:
            raise HTTPException(status_code=400, detail="quiz_id is required when intent is quiz_answer")
        quiz = await _get_owned_quiz(request.quiz_id, user, db)

    user_message = Message(chat_id=chat_id, role="user", content=request.content)
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)

    try:
        if quiz is not None:
            await request_evaluation(
                str(quiz.thread_id), request.content, str(chat_id), str(user_message.id), str(quiz.id)
            )
        else:
            await request_answer(str(chat_id), str(user_message.id), str(chat.document_id), request.content)
    except Exception as e:
        log.warning("chat_message_agentic_dispatch_failed", chat_id=str(chat_id), error=str(e))
        raise HTTPException(status_code=502, detail="Failed to dispatch question to agentic")

    log.info("chat_message_dispatched", chat_id=str(chat_id), user_id=str(user.id))
    return {"user_message": user_message}

# ---- Internal callbacks ----

INTERNAL_CALLBACK_TOKEN = os.getenv("INTERNAL_CALLBACK_TOKEN", "dev-internal-token")

class ChatAnswerCallbackRequest(BaseModel):
    chat_id: uuid.UUID
    message_id: uuid.UUID
    result: dict

def _extract_answer(result: dict) -> str:
    answer = result.get("answer")
    if answer is not None:
        return answer
    feedback = result.get("feedback")
    if feedback is not None:
        return feedback
    return json.dumps({k: v for k, v in result.items() if k not in ("question", "document_id")})

@router.post("/internal/chat-answers")
async def receive_chat_answer(
    request: ChatAnswerCallbackRequest,
    db: AsyncSession = Depends(get_db),
    x_internal_token: str = Header(None, alias="X-Internal-Token"),
):
    if x_internal_token != INTERNAL_CALLBACK_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid internal token")

    chat = await db.get(Chat, request.chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    answer = _extract_answer(request.result)
    assistant_message = Message(chat_id=request.chat_id, role="assistant", content=answer)
    db.add(assistant_message)

    quiz = None
    if request.result.get("intent") == "quiz":
        quiz = Quiz(
            document_id=chat.document_id,
            topic=request.result.get("question", "Chat quiz"),
            questions=request.result.get("quiz_questions", []),
            thread_id=request.result.get("thread_id"),
        )
        db.add(quiz)

    attempt = None
    if request.result.get("intent") == "quiz_answer":
        attempt = QuizAttempt(
            quiz_id=request.result.get("quiz_id"),
            user_id=chat.user_id,
            answers={"feedback": request.result.get("feedback")},
            score=request.result.get("score"),
        )
        db.add(attempt)

    await db.commit()
    await db.refresh(assistant_message)
    if quiz:
        await db.refresh(quiz)
    if attempt:
        await db.refresh(attempt)

    notify_quiz_id = str(quiz.id) if quiz else (str(attempt.quiz_id) if attempt else None)
    try:
        celery_app.send_task(
            "notify_quiz_ready",
            args=[str(chat.user_id)],
            kwargs={
                "quiz_id": notify_quiz_id,
                "chat_id": str(request.chat_id),
                "message_id": str(assistant_message.id),
            },
        )
    except Exception as e:
        log.warning("chat_answer_notify_dispatch_failed", chat_id=str(request.chat_id), error=str(e))

    return {"received": True}
