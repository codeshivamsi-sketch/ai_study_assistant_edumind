# Phase B5 — Chat-per-Document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add chat-per-document Q&A to core-api: `chats` and `messages` tables, five ownership-scoped endpoints, and a synchronous call into the agentic service's `/agent` for answers.

**Architecture:** Two new SQLAlchemy models (`Chat`, `Message`) + one Alembic migration, following the exact table/index/FK conventions of the existing schema. Routes live in the existing flat `routes.py`. The message-send endpoint inserts the user's message, commits it, then calls agentic's `POST /agent` synchronously (60s timeout, same `AGENTIC_SERVICE_URL` pattern as document upload) and inserts the assistant reply — or returns 502 with the user row already persisted.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Alembic, httpx (async client), pytest + pytest-asyncio + httpx `ASGITransport`.

## Global Constraints

- Ownership checks return 404, never 403 (CLAUDE.md invariant).
- `chats.user_id` and `chats.document_id` are `ON DELETE CASCADE`; `messages.chat_id` is `ON DELETE CASCADE` (per spec — these are not score-history rows like `quiz_attempts`, so no `RESTRICT`).
- Server-generated UUID PKs via `server_default=text("gen_random_uuid()")`, timezone-aware `created_at`, index only FK columns — exactly as in `models.py`.
- Tests hit a real Postgres (`postgresql+asyncpg://edumind:edumind@localhost:5432/edumind`) — `make up` (or `docker-compose up -d postgres`) must be running, and `alembic upgrade head` must have been run, before any test task in this plan.
- New async tests need `@pytest.mark.asyncio` (no `asyncio_mode=auto`).
- Seeded users: `ALICE_ID = "11111111-1111-1111-1111-111111111111"`, `BOB_ID = "22222222-2222-2222-2222-222222222222"`.

## Resolved ambiguities (see chat discussion for full rationale)

1. **`/agent`'s orchestrator has three intents** (`answer`, `quiz`, `summarize` — `services/agentic/agents/agents.py:11-19`), not two. Only `answer` sets an `"answer"` key on the response; `quiz` sets `"quiz_questions"`, `summarize` sets `"summary"`. The extraction logic treats both non-answer cases identically: JSON-serialize the response body (minus the echoed `question`/`document_id` fields) into `content`. This covers the quiz case the spec called out, and the summarize case it didn't.
2. **Mocking convention**: this repo's existing agentic-call tests (`tests/test_document_upload_route.py`) monkeypatch the routes-level imported function name, not raw `httpx`. This plan follows that convention: `agentic_client.ask_question` is monkeypatched as `routes.ask_question`.

---

### Task 1: `chats` / `messages` schema — migration + models

**Files:**
- Create: `services/core-api/migrations/versions/d3f6a91c8e27_create_chats_and_messages.py`
- Modify: `services/core-api/models.py`

**Interfaces:**
- Produces: `models.Chat` (`id`, `user_id`, `document_id`, `title`, `created_at`), `models.Message` (`id`, `chat_id`, `role`, `content`, `created_at`) — later tasks import both from `models`.

- [ ] **Step 1: Write the migration**

```python
"""create chats and messages

Revision ID: d3f6a91c8e27
Revises: e64775fbbdec
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'd3f6a91c8e27'
down_revision: Union[str, Sequence[str], None] = 'e64775fbbdec'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'chats',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['document_id'], ['documents.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_chats_user_id'), 'chats', ['user_id'], unique=False)
    op.create_index(op.f('ix_chats_document_id'), 'chats', ['document_id'], unique=False)

    op.create_table(
        'messages',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('chat_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('content', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('user','assistant')", name='messages_role_check'),
        sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_messages_chat_id'), 'messages', ['chat_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('messages')
    op.drop_table('chats')
```

- [ ] **Step 2: Add the models**

In `services/core-api/models.py`, add `Optional` to the typing import on line 1's neighbor and append the two classes:

```python
from typing import Optional
```

(add this import line near the top, alongside the existing imports)

```python
class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant')", name="messages_role_check"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("chats.id", ondelete="CASCADE"), index=True, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

- [ ] **Step 3: Run the migration**

```bash
cd services/core-api && alembic upgrade head
```
Expected: no errors; `alembic current` shows `d3f6a91c8e27 (head)`.

- [ ] **Step 4: Verify downgrade/upgrade round-trips cleanly**

```bash
cd services/core-api && alembic downgrade -1 && alembic upgrade head
```
Expected: both succeed with no errors (proves the migration is reversible before other tasks build on it).

- [ ] **Step 5: Commit**

```bash
git add services/core-api/migrations/versions/d3f6a91c8e27_create_chats_and_messages.py services/core-api/models.py
git commit -m "feat(core-api): add chats and messages tables"
```

---

### Task 2: `agentic_client.ask_question`

**Files:**
- Modify: `services/core-api/agentic_client.py`

**Interfaces:**
- Consumes: `AGENTIC_SERVICE_URL` (module-level, already defined).
- Produces: `async def ask_question(document_id: str, question: str) -> str` — later tasks import this into `routes.py` and monkeypatch it as `routes.ask_question` in tests.

- [ ] **Step 1: Add the function**

```python
import json
```
(add to the top imports, alongside `os` and `httpx`)

```python
async def ask_question(document_id: str, question: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{AGENTIC_SERVICE_URL}/agent",
            json={"question": question, "document_id": document_id},
        )
        response.raise_for_status()
        data = response.json()
    answer = data.get("answer")
    if answer is not None:
        return answer
    return json.dumps({k: v for k, v in data.items() if k not in ("question", "document_id")})
```

There's no standalone test for this function (mirrors `upload_document`, which is likewise only exercised through the route it backs) — Task 4's message-endpoint tests cover it via the `routes.ask_question` monkeypatch.

- [ ] **Step 2: Commit**

```bash
git add services/core-api/agentic_client.py
git commit -m "feat(core-api): add ask_question agentic client call"
```

---

### Task 3: Chat CRUD endpoints (`POST /chats`, `GET /chats`, `GET /chats/{chat_id}`)

**Files:**
- Create: `services/core-api/tests/test_chats_route.py`
- Modify: `services/core-api/routes.py`

**Interfaces:**
- Consumes: `models.Chat`, `models.Message` (Task 1); `_get_owned_document` (existing, `routes.py:27`).
- Produces: `_get_owned_chat(chat_id: uuid.UUID, user: User, db: AsyncSession) -> Chat` — Task 4 reuses this for the message endpoints.

- [ ] **Step 1: Write the failing tests**

Create `services/core-api/tests/test_chats_route.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/core-api && pytest tests/test_chats_route.py -v
```
Expected: FAIL — `404 Not Found` (no `/chats` route registered yet).

- [ ] **Step 3: Implement the endpoints**

In `services/core-api/routes.py`, add `Chat` and `Message` to the `models` import on line 10:

```python
from models import User, Document, Quiz, QuizAttempt, Chat, Message
```

Add `ask_question` to the `agentic_client` import on line 13:

```python
from agentic_client import upload_document, ask_question
```

Append a new `# ---- Chats ----` section after the quiz-attempts section (after `get_quiz_stats`, i.e. after line 237):

```python
# ---- Chats ----

class ChatCreateRequest(BaseModel):
    document_id: uuid.UUID
    title: Optional[str] = None

class MessageCreateRequest(BaseModel):
    content: str

async def _get_owned_chat(chat_id: uuid.UUID, user: User, db: AsyncSession) -> Chat:
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id)
    )
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat

@router.post("/chats")
async def create_chat(
    request: ChatCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = await _get_owned_document(request.document_id, user, db)
    if document.status != "ready":
        raise HTTPException(status_code=409, detail="Document not ready for chat")
    chat = Chat(user_id=user.id, document_id=request.document_id, title=request.title)
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    log.info("chat_created", chat_id=str(chat.id), document_id=str(document.id), user_id=str(user.id))
    return chat

@router.get("/chats")
async def list_chats(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    result = await db.execute(
        select(Chat).where(Chat.user_id == user.id).order_by(Chat.created_at.desc())
    )
    return result.scalars().all()

@router.get("/chats/{chat_id}")
async def get_chat(
    chat_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    return await _get_owned_chat(chat_id, user, db)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/core-api && pytest tests/test_chats_route.py -v
```
Expected: PASS (all 5 tests).

- [ ] **Step 5: Lint**

```bash
cd services/core-api && ruff check .
```
Expected: only the pre-existing `F401` findings noted in CLAUDE.md's Gotchas (no new findings).

- [ ] **Step 6: Commit**

```bash
git add services/core-api/routes.py services/core-api/tests/test_chats_route.py
git commit -m "feat(core-api): add chat CRUD endpoints"
```

---

### Task 4: Message endpoints (`POST /chats/{chat_id}/messages`, `GET /chats/{chat_id}/messages`)

**Files:**
- Modify: `services/core-api/tests/test_chats_route.py`
- Modify: `services/core-api/routes.py`

**Interfaces:**
- Consumes: `_get_owned_chat` (Task 3), `ask_question` (Task 2), `models.Message` (Task 1).

- [ ] **Step 1: Write the failing tests**

Append to `services/core-api/tests/test_chats_route.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/core-api && pytest tests/test_chats_route.py -v -k "message"
```
Expected: FAIL — `404 Not Found` (no `/chats/{chat_id}/messages` route yet).

- [ ] **Step 3: Implement the endpoints**

Append to the `# ---- Chats ----` section in `services/core-api/routes.py` (after `get_chat`):

```python
@router.get("/chats/{chat_id}/messages")
async def list_messages(
    chat_id: uuid.UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
):
    await _get_owned_chat(chat_id, user, db)
    result = await db.execute(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.asc())
    )
    return result.scalars().all()

@router.post("/chats/{chat_id}/messages")
async def create_message(
    chat_id: uuid.UUID,
    request: MessageCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    chat = await _get_owned_chat(chat_id, user, db)
    user_message = Message(chat_id=chat_id, role="user", content=request.content)
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)

    try:
        answer = await ask_question(str(chat.document_id), request.content)
    except Exception as e:
        log.warning("chat_message_agentic_failed", chat_id=str(chat_id), error=str(e))
        raise HTTPException(status_code=502, detail="Failed to get an answer")

    assistant_message = Message(chat_id=chat_id, role="assistant", content=answer)
    db.add(assistant_message)
    await db.commit()
    await db.refresh(assistant_message)
    log.info("chat_message_created", chat_id=str(chat_id), user_id=str(user.id))
    return {"user_message": user_message, "assistant_message": assistant_message}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd services/core-api && pytest tests/test_chats_route.py -v
```
Expected: PASS (all 9 tests in the file).

- [ ] **Step 5: Run the full test suite**

```bash
cd services/core-api && pytest tests/ -v
```
Expected: PASS, no regressions in `test_routes.py`, `test_document_upload_route.py`, `test_worker*.py`.

- [ ] **Step 6: Lint**

```bash
cd services/core-api && ruff check .
```
Expected: only the pre-existing `F401` findings.

- [ ] **Step 7: Commit**

```bash
git add services/core-api/routes.py services/core-api/tests/test_chats_route.py
git commit -m "feat(core-api): add chat message endpoints with agentic Q&A"
```

---

## Out of scope (explicitly not built this phase)

- No async/202 job + polling for message answers — `POST /chats/{chat_id}/messages` is synchronous only.
- No notifications-service involvement in chat answers.
- No changes to `services/agentic` — the `/agent` endpoint, its response shape, and the three-way intent classification are used as-is.
- No quiz-evaluation flow surfaced through chat — a `quiz`-classified answer is stored as opaque JSON text in `content`, not rendered as an interactive quiz.

## Post-implementation (per your request)

- [ ] Run `/blast` on the diff (models.py, routes.py, agentic_client.py, the new migration).
- [ ] Run `/arch` to regenerate `docs/architecture.md` — the new `chats`/`messages` tables and their CASCADE edges need to land in the ER diagram. (Reading "then h" as shorthand for `/arch`, per CLAUDE.md's documented "regenerate with /arch" flow — flag if you meant something else.)
