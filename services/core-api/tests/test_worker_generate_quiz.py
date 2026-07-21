import asyncio

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from database import DATABASE_URL
from main import app
from models import Quiz
from worker import generate_quiz

ALICE_ID = "11111111-1111-1111-1111-111111111111"


def auth(user_id: str) -> dict:
    return {"X-User-Id": user_id}


async def _create_ready_document() -> str:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/documents", json={"title": "Generate Quiz Test Doc", "status": "uploaded"}, headers=auth(ALICE_ID)
        )
        document = response.json()
        await client.patch(f"/documents/{document['id']}", json={"status": "ready"}, headers=auth(ALICE_ID))
        return document["id"]


async def _fetch_quiz(document_id: str):
    # Fresh engine per call, same reason as worker.py's _insert_quiz and
    # test_routes.py's own override_get_db: asyncio.run() gives this a new
    # event loop each time, and a shared/imported engine's pooled
    # connections would be bound to whatever loop touched them first.
    engine = create_async_engine(DATABASE_URL)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with SessionLocal() as session:
            result = await session.execute(select(Quiz).where(Quiz.document_id == document_id))
            return result.scalar_one_or_none()
    finally:
        await engine.dispose()


def test_generate_quiz_inserts_quiz_and_dispatches_notify(monkeypatch):
    document_id = asyncio.run(_create_ready_document())

    def fake_request_quiz(doc_id, topic):
        assert doc_id == document_id
        assert topic == "Chapter 2"
        return ["Q1: What is machine learning?"]

    monkeypatch.setattr("worker.request_quiz", fake_request_quiz)

    dispatched = {}

    def fake_send_task(name, args):
        dispatched["name"] = name
        dispatched["args"] = args

    monkeypatch.setattr("worker.celery_app.send_task", fake_send_task)

    result = generate_quiz.apply(args=[ALICE_ID, document_id, "Chapter 2"])

    assert result.successful()
    assert dispatched["name"] == "notify_quiz_ready"
    assert dispatched["args"][0] == ALICE_ID

    quiz = asyncio.run(_fetch_quiz(document_id))
    assert quiz is not None
    assert quiz.topic == "Chapter 2"
    assert quiz.questions == ["Q1: What is machine learning?"]
