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

        # Verify cross-user isolation: Bob's chat should not appear in Alice's list
        bob_document = await create_document(client, BOB_ID, "Bob's doc")
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

    monkeypatch.setattr("routes.request_answer", fake_request_answer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Async messages doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

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

    monkeypatch.setattr("routes.request_answer", failing_request_answer)

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
async def test_cross_user_chat_access_denied_matrix(monkeypatch):
    async def fake_request_answer(chat_id, message_id, document_id, question):
        return None

    monkeypatch.setattr("routes.request_answer", fake_request_answer)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Private chat doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        assert (await client.get(f"/chats/{chat['id']}/messages", headers=auth(BOB_ID))).status_code == 404
        assert (
            await client.post(
                f"/chats/{chat['id']}/messages", json={"content": "hijack"}, headers=auth(BOB_ID)
            )
        ).status_code == 404
