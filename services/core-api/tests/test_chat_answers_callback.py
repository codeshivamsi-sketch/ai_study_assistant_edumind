import pytest
from httpx import AsyncClient, ASGITransport

from main import app

ALICE_ID = "11111111-1111-1111-1111-111111111111"

INTERNAL_TOKEN_HEADER = {"X-Internal-Token": "dev-internal-token"}


def auth(user_id: str) -> dict:
    return {"X-User-Id": user_id}


async def _fake_upload_document(document_id, filename, content):
    pass


async def create_document(client: AsyncClient, monkeypatch, user_id: str, title: str) -> dict:
    monkeypatch.setattr("routes.upload_document", _fake_upload_document)
    response = await client.post(
        "/documents",
        data={"title": title},
        files={"file": ("doc.pdf", b"%PDF-fake-bytes", "application/pdf")},
        headers=auth(user_id),
    )
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
        document = await create_document(client, monkeypatch, ALICE_ID, "Callback doc")
        chat = await create_chat(client, ALICE_ID, document["id"])
        user_message = await create_user_message(client, chat["id"], "What is this about?")

        response = await client.post(
            "/internal/chat-answers",
            json={
                "chat_id": chat["id"],
                "message_id": user_message["id"],
                "result": {"intent": "answer", "answer": "This document is about photosynthesis."},
            },
            headers=INTERNAL_TOKEN_HEADER,
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
        document = await create_document(client, monkeypatch, ALICE_ID, "Quiz-intent doc")
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
            headers=INTERNAL_TOKEN_HEADER,
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
            headers=INTERNAL_TOKEN_HEADER,
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_callback_401s_with_wrong_or_missing_token():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "chat_id": "99999999-9999-9999-9999-999999999999",
            "message_id": "99999999-9999-9999-9999-999999999999",
            "result": {"intent": "answer", "answer": "x"},
        }

        response = await client.post("/internal/chat-answers", json=payload)
        assert response.status_code == 401

        response = await client.post(
            "/internal/chat-answers",
            json=payload,
            headers={"X-Internal-Token": "wrong-token"},
        )
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_callback_creates_quiz_attempt_for_quiz_answer_intent(monkeypatch):
    dispatched = {}

    def fake_send_task(name, args=None, kwargs=None):
        dispatched["name"] = name
        dispatched["args"] = args
        dispatched["kwargs"] = kwargs

    monkeypatch.setattr("routes.celery_app.send_task", fake_send_task)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Quiz-answer doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        quiz_seed_message = await create_user_message(client, chat["id"], "Quiz me")
        quiz_response = await client.post(
            "/internal/chat-answers",
            json={
                "chat_id": chat["id"],
                "message_id": quiz_seed_message["id"],
                "result": {
                    "intent": "quiz",
                    "question": "Quiz me",
                    "quiz_questions": ["Q1: What is a cell?"],
                    "thread_id": "thread-xyz",
                },
            },
            headers=INTERNAL_TOKEN_HEADER,
        )
        assert quiz_response.status_code == 200

        quizzes = await client.get("/quizzes", headers=auth(ALICE_ID))
        # Get the quiz created in this test (must match both topic and document)
        quiz = next((q for q in quizzes.json() if q["topic"] == "Quiz me" and str(q["document_id"]) == str(document["id"])), None)
        assert quiz is not None, "Quiz not found"

        user_message = await create_user_message(client, chat["id"], "A cell is the basic unit of life.")
        response = await client.post(
            "/internal/chat-answers",
            json={
                "chat_id": chat["id"],
                "message_id": user_message["id"],
                "result": {
                    "intent": "quiz_answer",
                    "quiz_id": quiz["id"],
                    "score": 8,
                    "feedback": "Correct and concise.",
                },
            },
            headers=INTERNAL_TOKEN_HEADER,
        )
        assert response.status_code == 200

        messages = await client.get(f"/chats/{chat['id']}/messages", headers=auth(ALICE_ID))
        contents = [(m["role"], m["content"]) for m in messages.json()]
        assert ("assistant", "Correct and concise.") in contents

        stats = await client.get(f"/quizzes/{quiz['id']}/stats", headers=auth(ALICE_ID))
        assert stats.json() == {"avg_score": 8.0, "attempt_count": 1}

    assert dispatched["kwargs"]["quiz_id"] == quiz["id"]
    assert dispatched["kwargs"]["chat_id"] == chat["id"]


@pytest.mark.asyncio
async def test_callback_400s_for_quiz_answer_with_unknown_quiz_id(monkeypatch):
    monkeypatch.setattr("routes.celery_app.send_task", lambda *a, **k: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Bad quiz-answer doc")
        chat = await create_chat(client, ALICE_ID, document["id"])
        user_message = await create_user_message(client, chat["id"], "A cell is the basic unit of life.")

        response = await client.post(
            "/internal/chat-answers",
            json={
                "chat_id": chat["id"],
                "message_id": user_message["id"],
                "result": {
                    "intent": "quiz_answer",
                    "quiz_id": "99999999-9999-9999-9999-999999999999",
                    "score": 8,
                    "feedback": "Correct and concise.",
                },
            },
            headers=INTERNAL_TOKEN_HEADER,
        )
        assert response.status_code == 400

        messages = await client.get(f"/chats/{chat['id']}/messages", headers=auth(ALICE_ID))
        roles = [m["role"] for m in messages.json()]
        assert "assistant" not in roles
