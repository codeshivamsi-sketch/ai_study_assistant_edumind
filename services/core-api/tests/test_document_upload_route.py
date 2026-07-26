import pytest
from httpx import AsyncClient, ASGITransport

from main import app

ALICE_ID = "11111111-1111-1111-1111-111111111111"
BOB_ID = "22222222-2222-2222-2222-222222222222"


def auth(user_id: str) -> dict:
    return {"X-User-Id": user_id}


@pytest.mark.asyncio
async def test_upload_sets_ready_on_success(monkeypatch):
    async def fake_upload_document(document_id, filename, content):
        assert filename == "curriculum.pdf"
        assert content == b"%PDF-fake-bytes"

    monkeypatch.setattr("routes.upload_document", fake_upload_document)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/documents", json={"title": "Upload Test Doc", "status": "uploaded"}, headers=auth(ALICE_ID)
        )
        document = create_response.json()

        upload_response = await client.post(
            f"/documents/{document['id']}/upload",
            files={"file": ("curriculum.pdf", b"%PDF-fake-bytes", "application/pdf")},
            headers=auth(ALICE_ID),
        )

        assert upload_response.status_code == 200
        assert upload_response.json()["status"] == "ready"

        get_response = await client.get(f"/documents/{document['id']}", headers=auth(ALICE_ID))
        assert get_response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_upload_sets_failed_on_agentic_error(monkeypatch):
    async def failing_upload_document(document_id, filename, content):
        raise RuntimeError("agentic unreachable")

    monkeypatch.setattr("routes.upload_document", failing_upload_document)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/documents", json={"title": "Upload Fail Test Doc", "status": "uploaded"}, headers=auth(ALICE_ID)
        )
        document = create_response.json()

        upload_response = await client.post(
            f"/documents/{document['id']}/upload",
            files={"file": ("curriculum.pdf", b"%PDF-fake-bytes", "application/pdf")},
            headers=auth(ALICE_ID),
        )

        assert upload_response.status_code == 502

        get_response = await client.get(f"/documents/{document['id']}", headers=auth(ALICE_ID))
        assert get_response.json()["status"] == "failed"


@pytest.mark.asyncio
async def test_upload_404s_on_other_users_document(monkeypatch):
    async def fake_upload_document(document_id, filename, content):
        pass

    monkeypatch.setattr("routes.upload_document", fake_upload_document)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/documents", json={"title": "Alice's Doc", "status": "uploaded"}, headers=auth(ALICE_ID)
        )
        document = create_response.json()

        upload_response = await client.post(
            f"/documents/{document['id']}/upload",
            files={"file": ("curriculum.pdf", b"%PDF-fake-bytes", "application/pdf")},
            headers=auth(BOB_ID),
        )

        assert upload_response.status_code == 404
