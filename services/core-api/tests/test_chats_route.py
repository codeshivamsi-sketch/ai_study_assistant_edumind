import pytest
from httpx import AsyncClient, ASGITransport

from main import app

ALICE_ID = "11111111-1111-1111-1111-111111111111"
BOB_ID = "22222222-2222-2222-2222-222222222222"


def auth(user_id: str) -> dict:
    return {"X-User-Id": user_id}


async def _fake_upload_document(document_id, filename, content):
    pass


async def _failing_upload_document(document_id, filename, content):
    raise RuntimeError("agentic unreachable")


async def create_document(client: AsyncClient, monkeypatch, user_id: str, title: str) -> dict:
    """Creates a document via the atomic upload endpoint with a mocked successful
    ingestion — always lands as status="ready"."""
    monkeypatch.setattr("routes.upload_document", _fake_upload_document)
    response = await client.post(
        "/documents",
        data={"title": title},
        files={"file": ("doc.pdf", b"%PDF-fake-bytes", "application/pdf")},
        headers=auth(user_id),
    )
    assert response.status_code == 200
    return response.json()


async def create_not_ready_document(client: AsyncClient, monkeypatch, user_id: str, title: str) -> dict:
    """Creates a document whose ingestion fails, landing at status="failed" —
    the only reachable non-"ready" terminal state now that creation is atomic."""
    monkeypatch.setattr("routes.upload_document", _failing_upload_document)
    response = await client.post(
        "/documents",
        data={"title": title},
        files={"file": ("doc.pdf", b"%PDF-fake-bytes", "application/pdf")},
        headers=auth(user_id),
    )
    assert response.status_code == 502
    list_response = await client.get("/documents", headers=auth(user_id))
    matches = [d for d in list_response.json() if d["title"] == title]
    assert len(matches) == 1
    return matches[0]


async def create_chat(client: AsyncClient, user_id: str, document_id: str, title: str = "Chat") -> dict:
    response = await client.post(
        "/chats", json={"document_id": document_id, "title": title}, headers=auth(user_id)
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_create_chat_happy_path(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Chat notes")
        chat = await create_chat(client, ALICE_ID, document["id"], "My chat")
        assert chat["title"] == "My chat"
        assert chat["document_id"] == document["id"]


@pytest.mark.asyncio
async def test_create_chat_is_idempotent_per_document(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Idempotent doc")
        first = await create_chat(client, ALICE_ID, document["id"], "First title")
        second = await create_chat(client, ALICE_ID, document["id"], "Second title")

        assert first["id"] == second["id"]
        assert second["title"] == "First title"  # existing chat returned as-is, title arg ignored

        list_response = await client.get("/chats", headers=auth(ALICE_ID))
        matching = [c for c in list_response.json() if c["document_id"] == document["id"]]
        assert len(matching) == 1


@pytest.mark.asyncio
async def test_create_chat_409s_when_document_not_ready(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_not_ready_document(client, monkeypatch, ALICE_ID, "Not ready doc")
        response = await client.post(
            "/chats", json={"document_id": document["id"], "title": "Chat"}, headers=auth(ALICE_ID)
        )
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_chat_404s_on_other_users_document(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Alice's doc")
        response = await client.post(
            "/chats", json={"document_id": document["id"], "title": "Bob's chat"}, headers=auth(BOB_ID)
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_chat_404s_for_other_user(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Private doc")
        chat = await create_chat(client, ALICE_ID, document["id"])
        assert (await client.get(f"/chats/{chat['id']}", headers=auth(BOB_ID))).status_code == 404
        assert (await client.get(f"/chats/{chat['id']}", headers=auth(ALICE_ID))).status_code == 200


@pytest.mark.asyncio
async def test_list_chats_newest_first(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # One chat per document now — use two documents to test ordering.
        first_document = await create_document(client, monkeypatch, ALICE_ID, "First doc")
        first = await create_chat(client, ALICE_ID, first_document["id"], "First")
        second_document = await create_document(client, monkeypatch, ALICE_ID, "Second doc")
        second = await create_chat(client, ALICE_ID, second_document["id"], "Second")

        response = await client.get("/chats", headers=auth(ALICE_ID))
        assert response.status_code == 200
        ids = [c["id"] for c in response.json()]
        assert ids.index(second["id"]) < ids.index(first["id"])

        # Verify cross-user isolation: Bob's chat should not appear in Alice's list
        bob_document = await create_document(client, monkeypatch, BOB_ID, "Bob's doc")
        bob_chat = await create_chat(client, BOB_ID, bob_document["id"], "Bob's chat")

        response = await client.get("/chats", headers=auth(ALICE_ID))
        assert response.status_code == 200
        ids = [c["id"] for c in response.json()]
        assert bob_chat["id"] not in ids


@pytest.mark.asyncio
async def test_create_message_202s_and_dispatches_to_agentic(monkeypatch):
    dispatched = {}

    async def fake_request_answer(chat_id, message_id, document_id, question):
        dispatched["chat_id"] = chat_id
        dispatched["message_id"] = message_id
        dispatched["document_id"] = document_id
        dispatched["question"] = question

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Async messages doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        monkeypatch.setattr("routes.request_answer", fake_request_answer)

        response = await client.post(
            f"/chats/{chat['id']}/messages",
            json={"content": "What is chapter 1 about?"},
            headers=auth(ALICE_ID),
        )
        assert response.status_code == 202
        body = response.json()
        assert body["user_message"]["role"] == "user"
        assert body["user_message"]["content"] == "What is chapter 1 about?"
        assert "assistant_message" not in body

        assert dispatched["chat_id"] == chat["id"]
        assert dispatched["document_id"] == document["id"]
        assert dispatched["question"] == "What is chapter 1 about?"

        messages = await client.get(f"/chats/{chat['id']}/messages", headers=auth(ALICE_ID))
        roles = [m["role"] for m in messages.json()]
        assert roles == ["user"]  # assistant reply hasn't arrived yet — that's the callback's job


@pytest.mark.asyncio
async def test_create_message_502s_on_agentic_dispatch_failure_keeps_user_row(monkeypatch):
    async def failing_request_answer(chat_id, message_id, document_id, question):
        raise RuntimeError("agentic unreachable")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Failure doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        monkeypatch.setattr("routes.request_answer", failing_request_answer)

        response = await client.post(
            f"/chats/{chat['id']}/messages",
            json={"content": "Will this fail?"},
            headers=auth(ALICE_ID),
        )
        assert response.status_code == 502

        messages = await client.get(f"/chats/{chat['id']}/messages", headers=auth(ALICE_ID))
        roles = [m["role"] for m in messages.json()]
        assert roles == ["user"]


@pytest.mark.asyncio
async def test_cross_user_chat_access_denied_matrix(monkeypatch):
    async def fake_request_answer(chat_id, message_id, document_id, question):
        return None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Private chat doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        monkeypatch.setattr("routes.request_answer", fake_request_answer)

        assert (await client.get(f"/chats/{chat['id']}/messages", headers=auth(BOB_ID))).status_code == 404
        assert (
            await client.post(
                f"/chats/{chat['id']}/messages", json={"content": "hijack"}, headers=auth(BOB_ID)
            )
        ).status_code == 404


@pytest.mark.asyncio
async def test_create_message_400s_when_quiz_answer_missing_quiz_id(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Quiz answer doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        response = await client.post(
            f"/chats/{chat['id']}/messages",
            json={"content": "The answer is X.", "intent": "quiz_answer"},
            headers=auth(ALICE_ID),
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_message_404s_when_quiz_id_not_owned(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from database import DATABASE_URL
    from models import Quiz

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bob_document = await create_document(client, monkeypatch, BOB_ID, "Bob's doc")

        engine = create_async_engine(DATABASE_URL)
        SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as session:
            quiz = Quiz(document_id=bob_document["id"], topic="Bob's quiz", questions=[], thread_id="thread-1")
            session.add(quiz)
            await session.commit()
            await session.refresh(quiz)
            bob_quiz_id = str(quiz.id)
        await engine.dispose()

        alice_document = await create_document(client, monkeypatch, ALICE_ID, "Alice's doc")
        alice_chat = await create_chat(client, ALICE_ID, alice_document["id"])

        response = await client.post(
            f"/chats/{alice_chat['id']}/messages",
            json={"content": "hijack", "intent": "quiz_answer", "quiz_id": bob_quiz_id},
            headers=auth(ALICE_ID),
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_message_409s_when_quiz_has_no_thread_id(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from database import DATABASE_URL
    from models import Quiz

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Pre-migration doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        engine = create_async_engine(DATABASE_URL)
        SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as session:
            quiz = Quiz(document_id=document["id"], topic="No-thread quiz", questions=[])
            session.add(quiz)
            await session.commit()
            await session.refresh(quiz)
            quiz_id = str(quiz.id)
        await engine.dispose()

        response = await client.post(
            f"/chats/{chat['id']}/messages",
            json={"content": "The answer is X.", "intent": "quiz_answer", "quiz_id": quiz_id},
            headers=auth(ALICE_ID),
        )
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_message_dispatches_evaluation_for_quiz_answer_intent(monkeypatch):
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from database import DATABASE_URL
    from models import Quiz

    dispatched = {}

    async def fake_request_evaluation(thread_id, user_answer, chat_id, message_id, quiz_id):
        dispatched["thread_id"] = thread_id
        dispatched["user_answer"] = user_answer
        dispatched["chat_id"] = chat_id
        dispatched["message_id"] = message_id
        dispatched["quiz_id"] = quiz_id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, monkeypatch, ALICE_ID, "Quiz answer dispatch doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        engine = create_async_engine(DATABASE_URL)
        SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as session:
            quiz = Quiz(document_id=document["id"], topic="Alice's quiz", questions=[], thread_id="thread-abc")
            session.add(quiz)
            await session.commit()
            await session.refresh(quiz)
            quiz_id = str(quiz.id)
        await engine.dispose()

        monkeypatch.setattr("routes.request_evaluation", fake_request_evaluation)

        response = await client.post(
            f"/chats/{chat['id']}/messages",
            json={"content": "It's the mitochondria.", "intent": "quiz_answer", "quiz_id": quiz_id},
            headers=auth(ALICE_ID),
        )
        assert response.status_code == 202

        assert dispatched["thread_id"] == "thread-abc"
        assert dispatched["user_answer"] == "It's the mitochondria."
        assert dispatched["chat_id"] == chat["id"]
        assert dispatched["quiz_id"] == quiz_id
