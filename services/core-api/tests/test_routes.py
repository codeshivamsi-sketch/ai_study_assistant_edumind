from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from main import app
from database import get_db
import pytest
from httpx import AsyncClient, ASGITransport

DATABASE_URL = "postgresql+asyncpg://edumind:edumind@localhost:5432/edumind"

ALICE_ID = "11111111-1111-1111-1111-111111111111"
BOB_ID = "22222222-2222-2222-2222-222222222222"
UNKNOWN_ID = "99999999-9999-9999-9999-999999999999"
NONEXISTENT_ID = "00000000-0000-0000-0000-000000000000"


async def override_get_db():
    engine = create_async_engine(DATABASE_URL)
    AsyncTestSession = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncTestSession() as session:
        yield session
    await engine.dispose()


app.dependency_overrides[get_db] = override_get_db


def auth(user_id: str) -> dict:
    return {"X-User-Id": user_id}


async def create_document(client: AsyncClient, user_id: str, title: str) -> dict:
    response = await client.post("/documents", json={"title": title, "status": "uploaded"}, headers=auth(user_id))
    assert response.status_code == 200
    return response.json()


async def create_quiz(client: AsyncClient, user_id: str, document_id: str, topic: str) -> dict:
    response = await client.post(
        "/quizzes",
        json={"document_id": document_id, "topic": topic, "questions": [{"q": "2+2?", "a": "4"}]},
        headers=auth(user_id),
    )
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
async def test_document_crud_happy_path():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Chapter 1 notes")
        assert document["status"] == "uploaded"

        get_response = await client.get(f"/documents/{document['id']}", headers=auth(ALICE_ID))
        assert get_response.status_code == 200
        assert get_response.json()["title"] == "Chapter 1 notes"

        patch_response = await client.patch(
            f"/documents/{document['id']}", json={"status": "ready"}, headers=auth(ALICE_ID)
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["status"] == "ready"

        delete_response = await client.delete(f"/documents/{document['id']}", headers=auth(ALICE_ID))
        assert delete_response.status_code == 200

        after_delete = await client.get(f"/documents/{document['id']}", headers=auth(ALICE_ID))
        assert after_delete.status_code == 404


@pytest.mark.asyncio
async def test_quiz_crud_happy_path():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Chapter 2 notes")
        quiz = await create_quiz(client, ALICE_ID, document["id"], "Chapter 2 quiz")

        get_response = await client.get(f"/quizzes/{quiz['id']}", headers=auth(ALICE_ID))
        assert get_response.status_code == 200
        assert get_response.json()["topic"] == "Chapter 2 quiz"

        patch_response = await client.patch(
            f"/quizzes/{quiz['id']}", json={"topic": "Chapter 2 quiz (revised)"}, headers=auth(ALICE_ID)
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["topic"] == "Chapter 2 quiz (revised)"

        delete_response = await client.delete(f"/quizzes/{quiz['id']}", headers=auth(ALICE_ID))
        assert delete_response.status_code == 200


@pytest.mark.asyncio
async def test_create_quiz_on_other_users_document_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Alice's private notes")
        response = await client.post(
            "/quizzes",
            json={"document_id": document["id"], "topic": "Bob's quiz", "questions": []},
            headers=auth(BOB_ID),
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_quiz_attempt_and_stats_happy_path():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Stats notes")
        quiz = await create_quiz(client, ALICE_ID, document["id"], "Stats quiz")

        attempt1 = await client.post(
            "/quiz_attempts",
            json={"quiz_id": quiz["id"], "answers": {"1": "4"}, "score": 80},
            headers=auth(ALICE_ID),
        )
        assert attempt1.status_code == 200
        assert attempt1.json()["user_id"] == ALICE_ID

        attempt2 = await client.post(
            "/quiz_attempts",
            json={"quiz_id": quiz["id"], "answers": {"1": "4"}, "score": 100},
            headers=auth(ALICE_ID),
        )
        assert attempt2.status_code == 200

        stats = await client.get(f"/quizzes/{quiz['id']}/stats", headers=auth(ALICE_ID))
        assert stats.status_code == 200
        body = stats.json()
        assert body["attempt_count"] == 2
        assert body["avg_score"] == 90.0


@pytest.mark.asyncio
async def test_quiz_attempt_on_other_users_quiz_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Private quiz notes")
        quiz = await create_quiz(client, ALICE_ID, document["id"], "Private quiz")

        response = await client.post(
            "/quiz_attempts",
            json={"quiz_id": quiz["id"], "answers": {}, "score": 50},
            headers=auth(BOB_ID),
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_quiz_stats_other_user_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Stats privacy notes")
        quiz = await create_quiz(client, ALICE_ID, document["id"], "Stats privacy quiz")

        response = await client.get(f"/quizzes/{quiz['id']}/stats", headers=auth(BOB_ID))
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_missing_x_user_id_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/documents")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_unknown_user_id_returns_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/documents", headers=auth(UNKNOWN_ID))
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_nonexistent_document_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/documents/{NONEXISTENT_ID}", headers=auth(ALICE_ID))
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_nonexistent_quiz_returns_404():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/quizzes/{NONEXISTENT_ID}", headers=auth(ALICE_ID))
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_cross_user_access_denied_matrix():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Matrix notes")
        quiz = await create_quiz(client, ALICE_ID, document["id"], "Matrix quiz")

        assert (await client.get(f"/documents/{document['id']}", headers=auth(BOB_ID))).status_code == 404
        assert (
            await client.patch(f"/documents/{document['id']}", json={"title": "hijacked"}, headers=auth(BOB_ID))
        ).status_code == 404
        assert (await client.delete(f"/documents/{document['id']}", headers=auth(BOB_ID))).status_code == 404

        assert (await client.get(f"/quizzes/{quiz['id']}", headers=auth(BOB_ID))).status_code == 404
        assert (
            await client.patch(f"/quizzes/{quiz['id']}", json={"topic": "hijacked"}, headers=auth(BOB_ID))
        ).status_code == 404
        assert (await client.delete(f"/quizzes/{quiz['id']}", headers=auth(BOB_ID))).status_code == 404

        assert (
            await client.post(
                "/quiz_attempts",
                json={"quiz_id": quiz["id"], "answers": {}, "score": 0},
                headers=auth(BOB_ID),
            )
        ).status_code == 404
        assert (await client.get(f"/quizzes/{quiz['id']}/stats", headers=auth(BOB_ID))).status_code == 404

        # Alice's resources survived every failed Bob attempt above.
        assert (await client.get(f"/documents/{document['id']}", headers=auth(ALICE_ID))).status_code == 200
        assert (await client.get(f"/quizzes/{quiz['id']}", headers=auth(ALICE_ID))).status_code == 200
