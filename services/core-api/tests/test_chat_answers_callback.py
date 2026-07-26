import pytest
from httpx import AsyncClient, ASGITransport

from main import app

ALICE_ID = "11111111-1111-1111-1111-111111111111"


def auth(user_id: str) -> dict:
    return {"X-User-Id": user_id}


async def create_document(client: AsyncClient, user_id: str, title: str) -> dict:
    response = await client.post("/documents", json={"title": title, "status": "ready"}, headers=auth(user_id))
    assert response.status_code == 200
    return response.json()


async def create_chat(client: AsyncClient, user_id: str, document_id: str) -> dict:
    response = await client.post("/chats", json={"document_id": document_id, "title": "Chat"}, headers=auth(user_id))
    assert response.status_code == 200
    return response.json()


async def create_user_message(client: AsyncClient, chat_id: str, content: str) -> dict:
    # Inserted directly via the DB in these tests rather than through
    # POST /chats/{chat_id}/messages, since that endpoint's own behavior
    # (Task 4) is tested separately — this file tests the callback in
    # isolation given an already-existing user message.
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from database import DATABASE_URL
    from models import Message

    engine = create_async_engine(DATABASE_URL)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with SessionLocal() as session:
            message = Message(chat_id=chat_id, role="user", content=content)
            session.add(message)
            await session.commit()
            await session.refresh(message)
            return {"id": str(message.id)}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_callback_inserts_assistant_message_for_answer_intent(monkeypatch):
    dispatched = {}

    def fake_send_task(name, args=None, kwargs=None):
        dispatched["name"] = name
        dispatched["args"] = args
        dispatched["kwargs"] = kwargs

    monkeypatch.setattr("routes.celery_app.send_task", fake_send_task)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Callback doc")
        chat = await create_chat(client, ALICE_ID, document["id"])
        user_message = await create_user_message(client, chat["id"], "What is this about?")

        response = await client.post(
            "/internal/chat-answers",
            json={
                "chat_id": chat["id"],
                "message_id": user_message["id"],
                "result": {"intent": "answer", "answer": "This document is about photosynthesis."},
            },
        )
        assert response.status_code == 200

        messages = await client.get(f"/chats/{chat['id']}/messages", headers=auth(ALICE_ID))
        contents = [(m["role"], m["content"]) for m in messages.json()]
        assert ("assistant", "This document is about photosynthesis.") in contents

    assert dispatched["name"] == "notify_quiz_ready"
    assert dispatched["kwargs"]["quiz_id"] is None
    assert dispatched["kwargs"]["chat_id"] == chat["id"]


@pytest.mark.asyncio
async def test_callback_creates_quiz_row_for_quiz_intent(monkeypatch):
    monkeypatch.setattr("routes.celery_app.send_task", lambda *a, **k: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Quiz-intent doc")
        chat = await create_chat(client, ALICE_ID, document["id"])
        user_message = await create_user_message(client, chat["id"], "Quiz me on chapter 1")

        response = await client.post(
            "/internal/chat-answers",
            json={
                "chat_id": chat["id"],
                "message_id": user_message["id"],
                "result": {
                    "intent": "quiz",
                    "question": "Quiz me on chapter 1",
                    "quiz_questions": ["Q1: What is a cell?"],
                },
            },
        )
        assert response.status_code == 200

        quizzes = await client.get("/quizzes", headers=auth(ALICE_ID))
        topics = [q["topic"] for q in quizzes.json()]
        assert "Quiz me on chapter 1" in topics


@pytest.mark.asyncio
async def test_callback_404s_for_nonexistent_chat():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/internal/chat-answers",
            json={
                "chat_id": "99999999-9999-9999-9999-999999999999",
                "message_id": "99999999-9999-9999-9999-999999999999",
                "result": {"intent": "answer", "answer": "x"},
            },
        )
        assert response.status_code == 404
