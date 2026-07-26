# Async Quiz-Answer Evaluation Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a client reply to a quiz question inside an existing chat and get it evaluated asynchronously, reusing the exact enqueue → RQ worker → callback → notify skeleton `POST /chats/{chat_id}/messages` already uses for regular chat answers.

**Architecture:** `POST /chats/{chat_id}/messages` gains an optional `intent`/`quiz_id`. When `intent == "quiz_answer"`, core-api looks up the owned `Quiz` row's `thread_id` (a new column) and fires a fast HTTP call to agentic's `/evaluate` (now enqueue-and-ack, 202, mirroring `/agent`). Agentic's RQ worker resumes the paused LangGraph checkpoint, runs the (now structured-JSON-output) evaluator node, and POSTs the result to the existing `POST /internal/chat-answers` callback, which gets a new `"quiz_answer"` branch that inserts a `QuizAttempt` row and an assistant `Message`, then dispatches the existing `notify_quiz_ready` task.

**Tech Stack:** FastAPI, RQ (agentic, existing queue), Celery (core-api, existing), Alembic (new migration — first core-api schema change since chats/messages), Anthropic SDK (evaluator prompt change), pytest + pytest-asyncio + httpx `ASGITransport` (core-api), pytest (agentic, existing `tests/test_jobs.py`).

## Global Constraints

- Ownership checks on `documents`, `quizzes`, and `quiz_attempts` always return **404**, never 403 — a resource the caller doesn't own must be indistinguishable from one that doesn't exist. `quiz_attempts` are reachable only through the `quizzes` they belong to, which are reachable only through `documents.user_id` — always join back to `documents.user_id` to authorize.
- `quiz_attempts.quiz_id` and `quiz_attempts.user_id` are `ON DELETE RESTRICT` — nothing in this plan touches that.
- Tests hit a real Postgres (`postgresql+asyncpg://edumind:edumind@localhost:5432/edumind`) — `make up`/`docker-compose up` must have `postgres` running for any `pytest` step below to pass. No rollback between tests.
- New async tests need an explicit `@pytest.mark.asyncio` decorator (`asyncio_mode=auto` is not configured).
- Imports in `services/core-api` and `services/agentic` are bare (`from routes import router`, `from core.jobs import ...`) — they only resolve with the respective service directory as CWD.
- `ruff check .` runs as a PostToolUse hook — don't introduce new unused imports.
- `services/agentic/api/main.py` currently has an **unrelated, pre-existing staged change** in the git index (removal of the old `/query` endpoint) that predates this plan. Task 3 edits this same file on top of that already-staged diff — don't revert or fight it, and don't include unrelated staged hunks when committing (use pathspec-scoped `git commit -- <files>`, not `git commit -a` or a bare `git add -A`).

---

### Task 1: Add `thread_id` column to `quizzes`

**Files:**
- Modify: `services/core-api/models.py:29-36` (`Quiz` class)
- Create: `services/core-api/migrations/versions/b7e14f9a2c63_add_thread_id_to_quizzes.py`
- Test: `services/core-api/tests/test_quiz_thread_id_column.py`

**Interfaces:**
- Produces: `Quiz.thread_id: Optional[str]` — Task 4 sets it when creating a `Quiz` row from the chat quiz-intent callback; Task 5 reads it to dispatch an evaluation.

- [ ] **Step 1: Write the failing test**

Create `services/core-api/tests/test_quiz_thread_id_column.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from database import DATABASE_URL
from models import Document, Quiz

ALICE_ID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.asyncio
async def test_quiz_thread_id_column_persists():
    engine = create_async_engine(DATABASE_URL)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with SessionLocal() as session:
            document = Document(user_id=ALICE_ID, title="Thread id doc", status="ready")
            session.add(document)
            await session.commit()
            await session.refresh(document)

            quiz = Quiz(document_id=document.id, topic="Thread id quiz", questions=[], thread_id="thread-42")
            session.add(quiz)
            await session.commit()
            await session.refresh(quiz)

            assert quiz.thread_id == "thread-42"
    finally:
        await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/core-api && ./.venv/bin/python -m pytest tests/test_quiz_thread_id_column.py -v`
Expected: FAIL with `TypeError: 'thread_id' is an invalid keyword argument for Quiz` (column/attribute doesn't exist yet).

- [ ] **Step 3: Add the column to the model**

In `services/core-api/models.py`, replace the `Quiz` class:

```python
class Quiz(Base):
    __tablename__ = "quizzes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()"))
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True, nullable=False)
    topic: Mapped[str] = mapped_column(String, nullable=False)
    questions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    thread_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
```

(`Optional` is already imported at the top of `models.py`.)

- [ ] **Step 4: Write the migration**

Create `services/core-api/migrations/versions/b7e14f9a2c63_add_thread_id_to_quizzes.py`:

```python
"""add thread_id to quizzes

Revision ID: b7e14f9a2c63
Revises: d3f6a91c8e27
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e14f9a2c63'
down_revision: Union[str, Sequence[str], None] = 'd3f6a91c8e27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('quizzes', sa.Column('thread_id', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('quizzes', 'thread_id')
```

- [ ] **Step 5: Apply the migration**

```bash
cd services/core-api
alembic upgrade head
```
Expected: `Running upgrade d3f6a91c8e27 -> b7e14f9a2c63, add thread_id to quizzes`

- [ ] **Step 6: Run test to verify it passes**

Run: `cd services/core-api && ./.venv/bin/python -m pytest tests/test_quiz_thread_id_column.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add services/core-api/models.py \
  services/core-api/migrations/versions/b7e14f9a2c63_add_thread_id_to_quizzes.py \
  services/core-api/tests/test_quiz_thread_id_column.py
git commit -m "feat(core-api): add thread_id column to quizzes"
```

---

### Task 2: Structured score/feedback output from `evaluator_node`

**Files:**
- Modify: `services/agentic/agents/agents.py:62-74` (`evaluator_node`)
- Modify: `services/agentic/core/model.py:9-19` (`EduMindState`)
- Test: `services/agentic/tests/test_agents.py` (new file — no existing tests for `agents.py`)

**Interfaces:**
- Produces: `evaluator_node(state) -> {"score": float, "feedback": str}` — Task 3's `run_evaluate_job` reads `result["evaluate"]["score"]`/`["feedback"]` from the LangGraph stream output.

- [ ] **Step 1: Write the failing test**

Create `services/agentic/tests/test_agents.py`:

```python
import json
from types import SimpleNamespace

from agents.agents import evaluator_node


def test_evaluator_node_parses_structured_score_and_feedback(monkeypatch):
    fake_json = json.dumps({"score": 7, "feedback": "Good grasp of the basics, missed the light-independent reactions."})
    fake_response = SimpleNamespace(content=[SimpleNamespace(text=fake_json)])
    monkeypatch.setattr(
        "agents.agents.anthropic_client.messages.create",
        lambda **kwargs: fake_response,
    )

    state = {
        "chunks": ["Photosynthesis converts light energy into chemical energy."],
        "quiz_questions": ["What is photosynthesis?"],
        "user_answer": "It's how plants make food from sunlight.",
    }

    result = evaluator_node(state)

    assert result == {
        "score": 7,
        "feedback": "Good grasp of the basics, missed the light-independent reactions.",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/agentic && python3 -m pytest tests/test_agents.py -v`
Expected: FAIL — `evaluator_node` currently returns `{"evaluation": ...}`, not `{"score": ..., "feedback": ...}`.

- [ ] **Step 3: Update `EduMindState`**

In `services/agentic/core/model.py`, in the `EduMindState` class, replace:
```python
    evaluation: str
```
with:
```python
    score: float
    feedback: str
```

- [ ] **Step 4: Update `evaluator_node`**

In `services/agentic/agents/agents.py`, add `import json` to the top imports (after `from langgraph.graph import StateGraph, END`), and replace `evaluator_node`:

```python
def evaluator_node(state: EduMindState):
    print("EVALUATOR RUNNING")
    context = "\n\n".join(state["chunks"])
    quiz = state["quiz_questions"]
    user_answer = state["user_answer"]

    response = anthropic_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=512,
        system=(
            "You are an evaluator. Score the user's answer against the quiz questions "
            "and context. Respond with ONLY a JSON object of the form "
            '{"score": <number 0-10>, "feedback": "<what was correct and what was missing>"}, '
            "no other text."
        ),
        messages=[{"role": "user", "content": f"Quiz Questions:\n{quiz}\n\nUser Answer:\n{user_answer}\n\nContext:\n{context}"}]
    )
    parsed = json.loads(response.content[0].text)
    return {"score": parsed["score"], "feedback": parsed["feedback"]}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/agentic && python3 -m pytest tests/test_agents.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/agentic/agents/agents.py services/agentic/core/model.py services/agentic/tests/test_agents.py
git commit -m "feat(agentic): evaluator_node returns structured score/feedback"
```

---

### Task 3: `/evaluate` becomes enqueue-and-ack + `run_evaluate_job`

**Files:**
- Modify: `services/agentic/core/model.py:29-31` (`EvaluateRequest`)
- Modify: `services/agentic/api/main.py:43-75` (`evaluate_endpoint`) — see the pre-existing-staged-diff note in Global Constraints before editing this file
- Modify: `services/agentic/core/jobs.py` (add `run_evaluate_job`)
- Test: `services/agentic/tests/test_jobs.py` (extend)

**Interfaces:**
- Consumes: `evaluator_node`'s `{"score", "feedback"}` shape (Task 2), `core.queue_client.job_queue` (existing).
- Produces: `core.jobs.run_evaluate_job(thread_id, user_answer, chat_id, message_id, quiz_id) -> None`, which POSTs `{chat_id, message_id, result: {"intent": "quiz_answer", "quiz_id", "score", "feedback"}}` to `POST /internal/chat-answers` — Task 4's callback branch consumes exactly this shape.

- [ ] **Step 1: Write the failing tests**

Append to `services/agentic/tests/test_jobs.py`:

```python
def test_run_evaluate_job_posts_result_to_callback(monkeypatch):
    monkeypatch.setattr("core.jobs.agent.update_state", lambda config, values, as_node: None)
    monkeypatch.setattr(
        "core.jobs.agent.stream",
        lambda inp, config: iter([{"evaluate": {"score": 8, "feedback": "Solid answer."}}]),
    )

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json, headers, timeout):
        posted["url"] = url
        posted["json"] = json
        posted["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("core.jobs.httpx.post", fake_post)

    core.jobs.run_evaluate_job(
        thread_id="thread-abc",
        user_answer="Photosynthesis converts sunlight into energy.",
        chat_id="22222222-2222-2222-2222-222222222222",
        message_id="33333333-3333-3333-3333-333333333333",
        quiz_id="44444444-4444-4444-4444-444444444444",
    )

    assert posted["url"] == "http://localhost:8000/internal/chat-answers"
    assert posted["json"]["chat_id"] == "22222222-2222-2222-2222-222222222222"
    assert posted["json"]["message_id"] == "33333333-3333-3333-3333-333333333333"
    assert posted["json"]["result"] == {
        "intent": "quiz_answer",
        "quiz_id": "44444444-4444-4444-4444-444444444444",
        "score": 8,
        "feedback": "Solid answer.",
    }
    assert posted["headers"] == {"X-Internal-Token": core.jobs.INTERNAL_CALLBACK_TOKEN}


def test_run_evaluate_job_reraises_after_logging_callback_failure(monkeypatch, capsys):
    monkeypatch.setattr("core.jobs.agent.update_state", lambda config, values, as_node: None)
    monkeypatch.setattr(
        "core.jobs.agent.stream",
        lambda inp, config: iter([{"evaluate": {"score": 5, "feedback": "x"}}]),
    )

    def failing_post(url, json, headers, timeout):
        raise ConnectionError("core-api unreachable")

    monkeypatch.setattr("core.jobs.httpx.post", failing_post)

    with pytest.raises(ConnectionError):
        core.jobs.run_evaluate_job(
            thread_id="t", user_answer="a", chat_id="c", message_id="m", quiz_id="q"
        )

    captured = capsys.readouterr()
    assert "quiz_evaluation_callback_failed" in captured.out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/agentic && python3 -m pytest tests/test_jobs.py -v`
Expected: both new tests FAIL with `AttributeError: module 'core.jobs' has no attribute 'run_evaluate_job'`.

- [ ] **Step 3: Add `chat_id`/`message_id`/`quiz_id` to `EvaluateRequest`**

In `services/agentic/core/model.py`, replace:
```python
class EvaluateRequest(BaseModel):
    thread_id: str
    user_answer: str
```
with:
```python
class EvaluateRequest(BaseModel):
    thread_id: str
    user_answer: str
    chat_id: str
    message_id: str
    quiz_id: str
```

- [ ] **Step 4: Add `run_evaluate_job`**

Append to `services/agentic/core/jobs.py`:

```python
def run_evaluate_job(thread_id: str, user_answer: str, chat_id: str, message_id: str, quiz_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    agent.update_state(config, {"user_answer": user_answer}, as_node="quiz")

    result = None
    for state in agent.stream(None, config=config):
        result = state
    evaluation = result.get("evaluate", {})

    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "result": {
            "intent": "quiz_answer",
            "quiz_id": quiz_id,
            "score": evaluation.get("score"),
            "feedback": evaluation.get("feedback"),
        },
    }
    try:
        response = httpx.post(
            f"{CORE_API_CALLBACK_URL}/internal/chat-answers",
            json=payload,
            headers={"X-Internal-Token": INTERNAL_CALLBACK_TOKEN},
            timeout=30,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"quiz_evaluation_callback_failed chat_id={chat_id} message_id={message_id} error={exc}")
        raise
```

- [ ] **Step 5: Make `/evaluate` enqueue-and-ack**

In `services/agentic/api/main.py`, replace the whole `evaluate_endpoint` function (the synchronous `agent.get_state`/`update_state`/`stream` block) with:

```python
@app.post("/evaluate", status_code=202)
def evaluate_endpoint(request: EvaluateRequest):
    job_queue.enqueue(
        "core.jobs.run_evaluate_job",
        request.thread_id,
        request.user_answer,
        request.chat_id,
        request.message_id,
        request.quiz_id,
    )
    return {"accepted": True}
```

(`job_queue` is already imported at the top of this file via `from core.queue_client import job_queue`. Leave the rest of the file — including the pre-existing `/query`-removal diff already staged — untouched.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd services/agentic && python3 -m pytest tests/test_jobs.py tests/test_agents.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add services/agentic/core/model.py services/agentic/core/jobs.py services/agentic/api/main.py \
  services/agentic/tests/test_jobs.py
git commit -m "feat(agentic): /evaluate becomes enqueue-and-ack via run_evaluate_job"
```

---

### Task 4: Core-api callback — `quiz_answer` branch writes `QuizAttempt`

**Files:**
- Modify: `services/core-api/routes.py:283-338` (`_extract_answer`, `receive_chat_answer`)
- Test: `services/core-api/tests/test_chat_answers_callback.py` (extend)

**Interfaces:**
- Consumes: the payload shape Task 3's `run_evaluate_job` POSTs (`{chat_id, message_id, result: {"intent": "quiz_answer", "quiz_id", "score", "feedback"}}`); `Quiz.thread_id` (Task 1).
- Produces: sets `Quiz.thread_id` when a `Quiz` row is created from the existing `"quiz"`-intent branch — Task 5 reads this.

- [ ] **Step 1: Write the failing test**

Append to `services/core-api/tests/test_chat_answers_callback.py`:

```python
@pytest.mark.asyncio
async def test_callback_creates_quiz_attempt_for_quiz_answer_intent(monkeypatch):
    dispatched = {}

    def fake_send_task(name, args=None, kwargs=None):
        dispatched["name"] = name
        dispatched["args"] = args
        dispatched["kwargs"] = kwargs

    monkeypatch.setattr("routes.celery_app.send_task", fake_send_task)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Quiz-answer doc")
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
        quiz = next(q for q in quizzes.json() if q["topic"] == "Quiz me")

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/core-api && ./.venv/bin/python -m pytest tests/test_chat_answers_callback.py::test_callback_creates_quiz_attempt_for_quiz_answer_intent -v`
Expected: FAIL — the assistant message will contain a JSON-dumped fallback blob (not "Correct and concise."), and `stats.json()` will show `attempt_count: 0`.

- [ ] **Step 3: Extend `_extract_answer`, and rewrite the rest of `receive_chat_answer`**

Replace `_extract_answer` to fall back to `feedback` before the generic JSON dump:

```python
def _extract_answer(result: dict) -> str:
    answer = result.get("answer")
    if answer is not None:
        return answer
    feedback = result.get("feedback")
    if feedback is not None:
        return feedback
    return json.dumps({k: v for k, v in result.items() if k not in ("question", "document_id")})
```

Then, in `receive_chat_answer`, replace the function body from `quiz = None` through the `return {"received": True}` with (this also adds `thread_id` to the existing `"quiz"`-intent branch, and adds the new `"quiz_answer"` branch):

```python
    quiz = None
    if request.result.get("intent") == "quiz":
        quiz = Quiz(
            document_id=chat.document_id,
            topic=request.result.get("question", "Chat quiz"),
            questions=request.result.get("quiz_questions", []),
            thread_id=request.result.get("thread_id"),
        )
        db.add(quiz)

    attempt = None
    if request.result.get("intent") == "quiz_answer":
        attempt = QuizAttempt(
            quiz_id=request.result.get("quiz_id"),
            user_id=chat.user_id,
            answers={"feedback": request.result.get("feedback")},
            score=request.result.get("score"),
        )
        db.add(attempt)

    await db.commit()
    await db.refresh(assistant_message)
    if quiz:
        await db.refresh(quiz)
    if attempt:
        await db.refresh(attempt)

    notify_quiz_id = str(quiz.id) if quiz else (str(attempt.quiz_id) if attempt else None)
    try:
        celery_app.send_task(
            "notify_quiz_ready",
            args=[str(chat.user_id)],
            kwargs={
                "quiz_id": notify_quiz_id,
                "chat_id": str(request.chat_id),
                "message_id": str(assistant_message.id),
            },
        )
    except Exception as e:
        log.warning("chat_answer_notify_dispatch_failed", chat_id=str(request.chat_id), error=str(e))

    return {"received": True}
```

(The lines above `quiz = None` — `chat = await db.get(...)`, the 404 check, building `assistant_message` — are unchanged; only the block from `quiz = None` onward is replaced.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/core-api && ./.venv/bin/python -m pytest tests/test_chat_answers_callback.py -v`
Expected: all PASS, including the existing `"quiz"`-intent test (it doesn't assert on `thread_id`, so adding the field doesn't break it).

- [ ] **Step 5: Commit**

```bash
git add services/core-api/routes.py services/core-api/tests/test_chat_answers_callback.py
git commit -m "feat(core-api): quiz_answer callback branch writes QuizAttempt"
```

---

### Task 5: `POST /chats/{chat_id}/messages` dispatches quiz-answer evaluation

**Files:**
- Modify: `services/core-api/agentic_client.py` (add `request_evaluation`)
- Modify: `services/core-api/routes.py:1-15,206-277` (imports, `MessageCreateRequest`, `create_message`)
- Test: `services/core-api/tests/test_chats_route.py` (extend)

**Interfaces:**
- Consumes: `Quiz.thread_id` (Task 1), `_get_owned_quiz` (existing helper).
- Produces: `agentic_client.request_evaluation(thread_id, user_answer, chat_id, message_id, quiz_id) -> None`, called from `create_message` when `intent == "quiz_answer"`.

- [ ] **Step 1: Write the failing tests**

Append to `services/core-api/tests/test_chats_route.py`:

```python
@pytest.mark.asyncio
async def test_create_message_400s_when_quiz_answer_missing_quiz_id():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Quiz answer doc")
        chat = await create_chat(client, ALICE_ID, document["id"])

        response = await client.post(
            f"/chats/{chat['id']}/messages",
            json={"content": "The answer is X.", "intent": "quiz_answer"},
            headers=auth(ALICE_ID),
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_create_message_404s_when_quiz_id_not_owned():
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from database import DATABASE_URL
    from models import Quiz

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        bob_document = await create_document(client, BOB_ID, "Bob's doc")

        engine = create_async_engine(DATABASE_URL)
        SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with SessionLocal() as session:
            quiz = Quiz(document_id=bob_document["id"], topic="Bob's quiz", questions=[], thread_id="thread-1")
            session.add(quiz)
            await session.commit()
            await session.refresh(quiz)
            bob_quiz_id = str(quiz.id)
        await engine.dispose()

        alice_document = await create_document(client, ALICE_ID, "Alice's doc")
        alice_chat = await create_chat(client, ALICE_ID, alice_document["id"])

        response = await client.post(
            f"/chats/{alice_chat['id']}/messages",
            json={"content": "hijack", "intent": "quiz_answer", "quiz_id": bob_quiz_id},
            headers=auth(ALICE_ID),
        )
        assert response.status_code == 404


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

    monkeypatch.setattr("routes.request_evaluation", fake_request_evaluation)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Quiz answer dispatch doc")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd services/core-api && ./.venv/bin/python -m pytest tests/test_chats_route.py -v`
Expected: the three new tests FAIL — `MessageCreateRequest` doesn't accept `intent`/`quiz_id` yet (422s instead of 400/404/202), and `routes.request_evaluation` doesn't exist.

- [ ] **Step 3: Add `request_evaluation` to `agentic_client.py`**

Append to `services/core-api/agentic_client.py`:

```python
async def request_evaluation(
    thread_id: str, user_answer: str, chat_id: str, message_id: str, quiz_id: str
) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{AGENTIC_SERVICE_URL}/evaluate",
            json={
                "thread_id": thread_id,
                "user_answer": user_answer,
                "chat_id": chat_id,
                "message_id": message_id,
                "quiz_id": quiz_id,
            },
        )
        response.raise_for_status()
```

- [ ] **Step 4: Update `routes.py`'s imports, `MessageCreateRequest`, and `create_message`**

Change the import line:
```python
from agentic_client import upload_document, request_answer
```
to:
```python
from agentic_client import upload_document, request_answer, request_evaluation
```

Replace `MessageCreateRequest`:
```python
class MessageCreateRequest(BaseModel):
    content: str
    intent: Optional[str] = None
    quiz_id: Optional[uuid.UUID] = None
```

Replace `create_message`:
```python
@router.post("/chats/{chat_id}/messages", status_code=202)
async def create_message(
    chat_id: uuid.UUID,
    request: MessageCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    chat = await _get_owned_chat(chat_id, user, db)

    quiz = None
    if request.intent == "quiz_answer":
        if request.quiz_id is None:
            raise HTTPException(status_code=400, detail="quiz_id is required when intent is quiz_answer")
        quiz = await _get_owned_quiz(request.quiz_id, user, db)

    user_message = Message(chat_id=chat_id, role="user", content=request.content)
    db.add(user_message)
    await db.commit()
    await db.refresh(user_message)

    try:
        if quiz is not None:
            await request_evaluation(
                str(quiz.thread_id), request.content, str(chat_id), str(user_message.id), str(quiz.id)
            )
        else:
            await request_answer(str(chat_id), str(user_message.id), str(chat.document_id), request.content)
    except Exception as e:
        log.warning("chat_message_agentic_dispatch_failed", chat_id=str(chat_id), error=str(e))
        raise HTTPException(status_code=502, detail="Failed to dispatch question to agentic")

    log.info("chat_message_dispatched", chat_id=str(chat_id), user_id=str(user.id))
    return {"user_message": user_message}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/core-api && ./.venv/bin/python -m pytest tests/test_chats_route.py -v`
Expected: all PASS, including the pre-existing message tests (the `intent`/`quiz_id` fields are optional and default to the old behavior).

- [ ] **Step 6: Commit**

```bash
git add services/core-api/agentic_client.py services/core-api/routes.py services/core-api/tests/test_chats_route.py
git commit -m "feat(core-api): dispatch quiz-answer evaluation from POST /chats/{chat_id}/messages"
```

---

## Out of scope (explicitly not built this phase)

- Any polling/job-status endpoint — matches the existing "no polling machinery" stance for the chat-answer flow.
- Retry/idempotency on the agentic → core-api callback for the evaluate path — matches the existing chat-answer callback's stance (Resolved Decision 5 in the prior async-chat-rq-pipeline plan).
- An endpoint-level test for `/evaluate` returning 202 in agentic (there's no equivalent test for `/agent` either — no `main.py` test file exists in that service yet; not introduced here).
- Changing how quizzes are generated, or the `interrupt_after=["quiz"]` LangGraph structure — only the resume/evaluate side changes.
- Guarding against answering the same quiz twice / resuming an already-completed LangGraph thread — the LangGraph checkpoint's own behavior in that case is unverified and left as-is; a second evaluation attempt fails through the existing 502 dispatch-failure path if the resume errors.

## Post-implementation

- [ ] Run the full suite for both touched services back to back, to confirm nothing outside the touched files regressed:
  ```bash
  cd services/core-api && ./.venv/bin/python -m pytest tests/ -v && ruff check .
  cd ../agentic && python3 -m pytest tests/ -v
  ```
  Expected: only the pre-existing `test_worker_retry.py` failure (if the retry-test Celery worker isn't running — see that test's own setup) is unexpected; everything else passes.
- [ ] Manually smoke-test the full loop once with `make up` running: create a document, upload it, create a chat, send a message that gets classified as `"quiz"` intent, confirm the resulting `Quiz` row has a non-null `thread_id` (`GET /quizzes` won't show it directly unless you inspect the DB — a quick `psql` check is fine), then send a second message with `intent=quiz_answer`/that `quiz_id` and confirm a `QuizAttempt` shows up via `GET /quizzes/{quiz_id}/stats`.
