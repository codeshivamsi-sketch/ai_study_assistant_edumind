import pytest
from httpx import AsyncClient, ASGITransport

from main import app

ALICE_ID = "11111111-1111-1111-1111-111111111111"


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
            "/documents",
            data={"title": "Upload Test Doc"},
            files={"file": ("curriculum.pdf", b"%PDF-fake-bytes", "application/pdf")},
            headers=auth(ALICE_ID),
        )

        assert create_response.status_code == 200
        document = create_response.json()
        assert document["status"] == "ready"

        get_response = await client.get(f"/documents/{document['id']}", headers=auth(ALICE_ID))
        assert get_response.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_upload_sets_failed_on_agentic_error(monkeypatch):
    async def failing_upload_document(document_id, filename, content):
        raise RuntimeError("agentic unreachable")

    monkeypatch.setattr("routes.upload_document", failing_upload_document)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/documents",
            data={"title": "Upload Fail Test Doc"},
            files={"file": ("curriculum.pdf", b"%PDF-fake-bytes", "application/pdf")},
            headers=auth(ALICE_ID),
        )

        assert create_response.status_code == 502

        list_response = await client.get("/documents", headers=auth(ALICE_ID))
        failed = [d for d in list_response.json() if d["title"] == "Upload Fail Test Doc"]
        assert len(failed) == 1
        assert failed[0]["status"] == "failed"
