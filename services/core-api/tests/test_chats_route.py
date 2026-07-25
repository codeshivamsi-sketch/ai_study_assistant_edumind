import pytest
from httpx import AsyncClient, ASGITransport

from main import app

ALICE_ID = "11111111-1111-1111-1111-111111111111"
BOB_ID = "22222222-2222-2222-2222-222222222222"


def auth(user_id: str) -> dict:
    return {"X-User-Id": user_id}


async def create_document(client: AsyncClient, user_id: str, title: str, status: str = "ready") -> dict:
    response = await client.post("/documents", json={"title": title, "status": status}, headers=auth(user_id))
    assert response.status_code == 200
    return response.json()


async def create_chat(client: AsyncClient, user_id: str, document_id: str, title: str = "Chat") -> dict:
    response = await client.post(
        "/chats", json={"document_id": document_id, "title": title}, headers=auth(user_id)
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_create_chat_happy_path():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Chat notes")
        chat = await create_chat(client, ALICE_ID, document["id"], "My chat")
        assert chat["title"] == "My chat"
        assert chat["document_id"] == document["id"]


@pytest.mark.asyncio
async def test_create_chat_409s_when_document_not_ready():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Not ready doc", status="uploaded")
        response = await client.post(
            "/chats", json={"document_id": document["id"], "title": "Chat"}, headers=auth(ALICE_ID)
        )
        assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_chat_404s_on_other_users_document():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Alice's doc")
        response = await client.post(
            "/chats", json={"document_id": document["id"], "title": "Bob's chat"}, headers=auth(BOB_ID)
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_chat_404s_for_other_user():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Private doc")
        chat = await create_chat(client, ALICE_ID, document["id"])
        assert (await client.get(f"/chats/{chat['id']}", headers=auth(BOB_ID))).status_code == 404
        assert (await client.get(f"/chats/{chat['id']}", headers=auth(ALICE_ID))).status_code == 200


@pytest.mark.asyncio
async def test_list_chats_newest_first():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "List doc")
        first = await create_chat(client, ALICE_ID, document["id"], "First")
        second = await create_chat(client, ALICE_ID, document["id"], "Second")

        response = await client.get("/chats", headers=auth(ALICE_ID))
        assert response.status_code == 200
        ids = [c["id"] for c in response.json()]
        assert ids.index(second["id"]) < ids.index(first["id"])


@pytest.mark.asyncio
async def test_create_message_happy_path(monkeypatch):
    async def fake_ask_question(document_id, question):
        assert question == "What is chapter 1 about?"
        return "Chapter 1 covers photosynthesis."

    monkeypatch.setattr("routes.ask_question", fake_ask_question)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Messages doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        response = await client.post(
            f"/chats/{chat['id']}/messages",
            json={"content": "What is chapter 1 about?"},
            headers=auth(ALICE_ID),
        )
        assert response.status_code == 200
        body = response.json()
        assert body["user_message"]["role"] == "user"
        assert body["user_message"]["content"] == "What is chapter 1 about?"
        assert body["assistant_message"]["role"] == "assistant"
        assert body["assistant_message"]["content"] == "Chapter 1 covers photosynthesis."

        messages = await client.get(f"/chats/{chat['id']}/messages", headers=auth(ALICE_ID))
        assert messages.status_code == 200
        roles = [m["role"] for m in messages.json()]
        assert roles == ["user", "assistant"]


@pytest.mark.asyncio
async def test_create_message_502s_on_agentic_failure_keeps_user_row(monkeypatch):
    async def failing_ask_question(document_id, question):
        raise RuntimeError("agentic unreachable")

    monkeypatch.setattr("routes.ask_question", failing_ask_question)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Failure doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

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
async def test_messages_ordered_by_created_at_asc(monkeypatch):
    answers = iter(["First answer.", "Second answer."])

    async def fake_ask_question(document_id, question):
        return next(answers)

    monkeypatch.setattr("routes.ask_question", fake_ask_question)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Ordering doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        await client.post(f"/chats/{chat['id']}/messages", json={"content": "First question"}, headers=auth(ALICE_ID))
        await client.post(f"/chats/{chat['id']}/messages", json={"content": "Second question"}, headers=auth(ALICE_ID))

        messages = await client.get(f"/chats/{chat['id']}/messages", headers=auth(ALICE_ID))
        contents = [m["content"] for m in messages.json()]
        assert contents == ["First question", "First answer.", "Second question", "Second answer."]


@pytest.mark.asyncio
async def test_cross_user_chat_access_denied_matrix(monkeypatch):
    async def fake_ask_question(document_id, question):
        return "answer"

    monkeypatch.setattr("routes.ask_question", fake_ask_question)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Private chat doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        assert (await client.get(f"/chats/{chat['id']}/messages", headers=auth(BOB_ID))).status_code == 404
        assert (
            await client.post(
                f"/chats/{chat['id']}/messages", json={"content": "hijack"}, headers=auth(BOB_ID)
            )
        ).status_code == 404
