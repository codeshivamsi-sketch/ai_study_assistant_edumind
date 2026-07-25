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
