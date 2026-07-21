# Phase B4 — Connect core-api to the agentic service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A client can request a quiz for one of their documents by topic;
`core-api` calls the agentic service's LLM/retrieval pipeline in the
background, inserts the resulting quiz, and notifies the client via the
existing Phase B3 notifications pipeline — without blocking the request.

**Architecture:** Add `document_id`-scoped ingestion/retrieval to the
agentic service (it currently has no document concept — one global Chroma
collection, no filtering). Add a real file-upload endpoint to `core-api`
that forwards into the agentic service. Add an async `generate_quiz`
Celery task that calls the agentic service, inserts the quiz, and reuses
the existing `notify_quiz_ready` task.

**Tech Stack:** FastAPI, SQLAlchemy 2.0 async, Celery 5.6 + Redis, httpx,
ChromaDB (`where` metadata filtering), python-multipart.

See `docs/superpowers/specs/2026-07-22-phase-b4-agentic-quiz-generation-design.md`
for the full rationale, including why the original plan's `document_id`
assumption didn't hold and what's explicitly deferred (Neo4j scoping,
document re-upload, job-status polling).

## Global Constraints

- Ownership checks on `documents` (and anything reached through them) are
  always **404**, never 403 or a bare validation error, when the resource
  exists but isn't the caller's — use the existing `_get_owned_document`
  helper in `services/core-api/routes.py`, never a new ad-hoc check.
- `python-multipart==0.0.32` (matches the version already proven working
  in the agentic service's own container) is the only new core-api
  dependency this plan adds.
- `AGENTIC_SERVICE_URL` env var (already set in `docker-compose.yml` since
  Phase B2) defaults to `http://localhost:8002` for local/non-compose runs
  — matches the agentic service's host-mapped port.
- The new Celery task is registered under the exact string name
  `"generate_quiz"` and dispatched via `celery_app.send_task("generate_quiz",
  args=[...])` — string-based dispatch, matching the existing
  `notify_quiz_ready` pattern (never import and call the task function
  directly from routes.py).
- `generate_quiz`'s retry (`max_retries=2`, `GENERATE_QUIZ_RETRY_COUNTDOWN`
  env var, default `30`) wraps **only** the agentic HTTP call. A DB-insert
  failure after a successful (expensive) LLM call is logged and returns —
  it never triggers `self.retry()` (that would re-run the expensive call
  to satisfy a cheap DB failure).
- Chroma chunk metadata key is `document_id` (string) — optional
  everywhere (agentic's existing callers — the MCP server, the eval
  harness — never pass one, and must keep working unscoped/globally).
- New/changed Python identifiers used across tasks — get these exact
  names right, later tasks depend on them:
  - `services/agentic/core/ingest.py`: `store_in_chroma(chunks, embeddings,
    document_id=None)`
  - `services/agentic/core/query.py`: `get_searched_chunks_from_chroma(question_embedding,
    document_id=None)`
  - `services/core-api/agentic_client.py`: `async def
    upload_document(document_id: str, filename: str, content: bytes) ->
    None` and `def request_quiz(document_id: str, topic: str) -> list`
  - `services/core-api/worker.py`: Celery task function `generate_quiz(self,
    user_id, document_id, topic)`, registered as `name="generate_quiz"`

---

### Task 1: Document-scoped ingestion and retrieval in the agentic service

**Files:**
- Modify: `services/agentic/core/model.py`
- Modify: `services/agentic/core/ingest.py`
- Modify: `services/agentic/core/query.py`
- Modify: `services/agentic/agents/agents.py`
- Modify: `services/agentic/api/main.py`

**Interfaces:**
- Produces: `store_in_chroma(chunks, embeddings, document_id=None)`,
  `get_searched_chunks_from_chroma(question_embedding, document_id=None)`
  — Task 3's `core-api` integration relies on `/agent` and `/upload`
  actually honoring `document_id` end-to-end, which this task delivers.
- No automated test suite exists yet for `services/agentic` (no
  `conftest.py`, no test files) — this task is verified manually via a
  curl + `docker exec` script (Step 5), not pytest. Introducing a full
  pytest harness for this service is out of scope for this plan.

- [ ] **Step 1: Update request/state models**

Edit `services/agentic/core/model.py`:

```python
from pydantic import BaseModel
from typing import List, Optional, TypedDict

class QueryRequest(BaseModel):
    question: str
    document_id: Optional[str] = None


class EduMindState(TypedDict):
    question: str
    document_id: str
    intent: str     # "answer", "quiz", "summarize", "evaluate"
    chunks: List[str]
    related_concepts: List[str]
    answer: str
    quiz_questions: List[str]
    summary: str
    user_answer: str
    evaluation: str


class AgentRequest(BaseModel):
    question: str
    document_id: Optional[str] = None


class EvaluateRequest(BaseModel):
    thread_id: str
    user_answer: str
```

- [ ] **Step 2: Tag chunks with document_id at ingest time**

Edit `services/agentic/core/ingest.py`, replace `store_in_chroma`:

```python
def store_in_chroma(chunks: list[str], embeddings: list, document_id: str | None = None):
    if document_id:
        ids = [f"{document_id}-{i}" for i in range(len(chunks))]
        metadatas = [{"document_id": document_id} for _ in chunks]
        collection.add(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metadatas)
    else:
        collection.add(
            documents=chunks,
            embeddings=embeddings,
            ids=[str(i) for i in range(len(chunks))]
        )
```

- [ ] **Step 3: Filter retrieval by document_id**

Edit `services/agentic/core/query.py`, replace
`get_searched_chunks_from_chroma`:

```python
def get_searched_chunks_from_chroma(question_embedding, document_id: str | None = None):
    query_kwargs = {"query_embeddings": [question_embedding], "n_results": 3}
    if document_id:
        query_kwargs["where"] = {"document_id": document_id}
    results = collection.query(**query_kwargs)
    chunks = results["documents"][0]
    print("Chunks from chroma: ", chunks)
    return chunks
```

- [ ] **Step 4: Thread document_id through the LangGraph retrieval node and the API**

Edit `services/agentic/agents/agents.py`, replace `retrieval_node`:

```python
def retrieval_node(state: EduMindState):
    question = state["question"]
    document_id = state.get("document_id")
    embedding = embed_ques(question)
    chunks = get_searched_chunks_from_chroma(embedding, document_id)
    related_concepts = get_related_from_graph(question)
    return {"chunks": chunks, "related_concepts": related_concepts}
```

Edit `services/agentic/api/main.py`:

```python
from fastapi import FastAPI, UploadFile, File, Form
import os
from typing import Optional
from core.ingest import save_pdf_on_disk, get_pdf_content, split_content_into_chunks, embed_chunks, store_in_chroma, ingest_graph
from core.query import embed_ques, get_searched_chunks_from_chroma, get_ans_from_claud, get_related_from_graph
import chromadb
from core.model import QueryRequest, AgentRequest, EvaluateRequest
from agents.agents import agent, evaluator_node
import uuid

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...), document_id: Optional[str] = Form(None)):
    await save_pdf_on_disk(file)
    pdf_content = get_pdf_content(f"uploads/{file.filename}")
    chunks = split_content_into_chunks(pdf_content)
    embeddings = embed_chunks(chunks)
    store_in_chroma(chunks, embeddings, document_id)
    ingest_graph(chunks)
    return {"filename": file.filename, "chunks": len(chunks), "document_id": document_id}


@app.post("/query")
def query_endpoint(request: QueryRequest):
    question = request.question
    question_embedding = embed_ques(question)
    chunks = get_searched_chunks_from_chroma(question_embedding, request.document_id)
    graph_concepts = get_related_from_graph(question)
    response = get_ans_from_claud(question, chunks, graph_concepts)
    return {
        "answer": response.content[0].text,
        "source_chunks": chunks,
        "related_concepts": graph_concepts
    }


@app.post("/agent")
def agent_endpoint(request: AgentRequest):
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"question": request.question, "document_id": request.document_id}, config=config)
    return {**result, "thread_id": thread_id}


@app.post("/evaluate")
def evaluate_endpoint(request: EvaluateRequest):
    try:
        config = {"configurable":{"thread_id":request.thread_id}}
        current_state = agent.get_state(config)
        agent.update_state(
            config,
            {"user_answer":request.user_answer},
            as_node="quiz"
        )
        result = None
        for state in agent.stream(None, config=config):
            result=state
        return {"evaluation":result.get("evaluate", {}).get("evaluation", "No evaluation")}
    except Exception as e:
        raise e
```

(Only `/upload`, `/query`, `/agent` actually changed — `/health` and
`/evaluate` are shown unchanged for context; don't reformat or touch
them beyond what's shown.)

- [ ] **Step 5: Rebuild and manually verify document scoping**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
docker-compose up -d --build agentic
sleep 10
curl -s http://localhost:8002/health
```

Expected: `{"status":"ok"}`.

```bash
curl -s -X POST http://localhost:8002/upload \
  -F "file=@services/agentic/uploads/test_curriculum.pdf" \
  -F "document_id=doc-scope-test-a"

curl -s -X POST http://localhost:8002/upload \
  -F "file=@services/agentic/uploads/test_curriculum.pdf" \
  -F "document_id=doc-scope-test-b"
```

Expected: both return `200` with `"document_id"` echoed back matching
what was sent, and matching `"chunks"` counts.

```bash
docker exec python_backend_refresher-agentic-1 python3 -c "
from core.config import collection
result_a = collection.get(where={'document_id': 'doc-scope-test-a'})
result_b = collection.get(where={'document_id': 'doc-scope-test-b'})
print('a count:', len(result_a['ids']), 'sample:', result_a['ids'][:2])
print('b count:', len(result_b['ids']), 'sample:', result_b['ids'][:2])
assert all(i.startswith('doc-scope-test-a-') for i in result_a['ids'])
assert all(i.startswith('doc-scope-test-b-') for i in result_b['ids'])
assert len(result_a['ids']) == len(result_b['ids']) > 0
print('OK: scoping verified')
"
```

Expected: prints `OK: scoping verified` with no assertion error — proves
the two uploads' chunks landed under distinct, correctly-prefixed ids
with no collision.

```bash
curl -s -X POST http://localhost:8002/agent \
  -H "Content-Type: application/json" \
  -d '{"question": "quiz me on machine learning", "document_id": "doc-scope-test-a"}'
```

Expected: `200`, a JSON body with `"intent":"quiz"`, non-empty
`"quiz_questions"`, and a `"thread_id"` — confirms `document_id` flows all
the way through `/agent` → `retrieval_node` → Chroma filter without
erroring.

- [ ] **Step 6: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/agentic/core/model.py services/agentic/core/ingest.py services/agentic/core/query.py services/agentic/agents/agents.py services/agentic/api/main.py
git commit -m "feat(agentic): add document_id-scoped ingestion and retrieval

Chunks are tagged with document_id metadata at /upload time and Chroma
queries filter by it when provided, both in /query and /agent. Optional
everywhere (default None = today's global/unscoped behavior), so the
MCP server and eval harness keep working unchanged."
```

---

### Task 2: core-api upload endpoint (forwards into the agentic service)

**Files:**
- Modify: `services/core-api/requirements.txt`
- Create: `services/core-api/agentic_client.py`
- Modify: `services/core-api/routes.py`
- Test: `services/core-api/tests/test_document_upload_route.py`

**Interfaces:**
- Consumes: `_get_owned_document` (existing helper, `routes.py`), `log`
  (existing `logger.py` export).
- Produces: `agentic_client.upload_document(document_id: str, filename:
  str, content: bytes) -> None` (raises on failure) — used only by this
  task's route; `agentic_client.request_quiz` (used by Task 3) lives in
  the same file but is added in Task 3, not here.

- [ ] **Step 1: Add the dependency**

Edit `services/core-api/requirements.txt`, insert alphabetically after
`python-dotenv==1.2.2`:

```
python-multipart==0.0.32
```

- [ ] **Step 2: Create the agentic HTTP client module**

Create `services/core-api/agentic_client.py`:

```python
import os
import httpx

AGENTIC_SERVICE_URL = os.getenv("AGENTIC_SERVICE_URL", "http://localhost:8002")


async def upload_document(document_id: str, filename: str, content: bytes) -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{AGENTIC_SERVICE_URL}/upload",
            files={"file": (filename, content, "application/pdf")},
            data={"document_id": document_id},
        )
        response.raise_for_status()
```

- [ ] **Step 3: Write the failing test**

Create `services/core-api/tests/test_document_upload_route.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd services/core-api && pytest tests/test_document_upload_route.py -v`
Expected: FAIL — `404 Not Found` for the new route (doesn't exist yet) or
an import error.

- [ ] **Step 5: Implement the route**

Edit `services/core-api/routes.py`. Replace the existing
`from fastapi import APIRouter, HTTPException, Depends` line with:

```python
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
```

Add a new import line directly after `from worker import celery_app`:

```python
from agentic_client import upload_document
```

Add after `delete_document` (still inside the `# ---- Documents ----`
section):

```python
@router.post("/documents/{document_id}/upload")
async def upload_document_file(
    document_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = await _get_owned_document(document_id, user, db)
    content = await file.read()
    document.status = "processing"
    await db.commit()
    try:
        await upload_document(str(document_id), file.filename, content)
    except Exception as e:
        document.status = "failed"
        await db.commit()
        log.warning("document_upload_failed", document_id=str(document_id), error=str(e))
        raise HTTPException(status_code=502, detail="Document ingestion failed")
    document.status = "ready"
    await db.commit()
    await db.refresh(document)
    log.info("document_uploaded", document_id=str(document_id))
    return document
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd services/core-api && pip install -r requirements.txt && pytest tests/test_document_upload_route.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 7: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/core-api/requirements.txt services/core-api/agentic_client.py services/core-api/routes.py services/core-api/tests/test_document_upload_route.py
git commit -m "feat(core-api): add POST /documents/{id}/upload, forwards into agentic

Ownership-checked (404 pattern), sets status processing -> ready/failed
around the forward. Deliberately synchronous (not Celery) -- small PDFs,
httpx.AsyncClient is true async I/O and doesn't block the event loop."
```

---

### Task 3: Async quiz generation (POST /quizzes/generate + generate_quiz task)

**Files:**
- Modify: `services/core-api/agentic_client.py`
- Modify: `services/core-api/routes.py`
- Modify: `services/core-api/worker.py`
- Test: `services/core-api/tests/test_worker_generate_quiz.py`

**Interfaces:**
- Consumes: `celery_app` (existing, `worker.py`), `Quiz` model (existing,
  `models.py`), `DATABASE_URL` (existing, `database.py` — a fresh engine is
  created per call from this, not the shared `AsyncSessionLocal`; see Step
  4's note on why), `_get_owned_document` (existing, `routes.py`).
- Produces: Celery task `generate_quiz(self, user_id, document_id, topic)`
  registered as `name="generate_quiz"`; `agentic_client.request_quiz(document_id:
  str, topic: str) -> list`.

- [ ] **Step 1: Add the sync agentic client function**

Edit `services/core-api/agentic_client.py`, add below `upload_document`:

```python
def request_quiz(document_id: str, topic: str) -> list:
    response = httpx.post(
        f"{AGENTIC_SERVICE_URL}/agent",
        json={"question": f"Quiz me on {topic}", "document_id": document_id},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["quiz_questions"]
```

- [ ] **Step 2: Write the failing test**

Create `services/core-api/tests/test_worker_generate_quiz.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd services/core-api && pytest tests/test_worker_generate_quiz.py -v`
Expected: FAIL — `ImportError: cannot import name 'generate_quiz' from 'worker'`.

- [ ] **Step 4: Implement the task**

Replace `services/core-api/worker.py` entirely with:

```python
import asyncio
import os

from celery import Celery
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from agentic_client import request_quiz
from database import DATABASE_URL
from grpc_client import notify_quiz_ready as send_grpc_notification
from logger import log
from models import Quiz

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RETRY_COUNTDOWN = int(os.getenv("NOTIFY_QUIZ_READY_RETRY_COUNTDOWN", "60"))
GENERATE_QUIZ_RETRY_COUNTDOWN = int(os.getenv("GENERATE_QUIZ_RETRY_COUNTDOWN", "30"))

celery_app = Celery(
    "core-api",
    broker=REDIS_URL,
    backend=REDIS_URL
)


@celery_app.task(bind=True, max_retries=3, name="notify_quiz_ready")
def notify_quiz_ready(self, user_id, quiz_id):
    try:
        send_grpc_notification(user_id, quiz_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=RETRY_COUNTDOWN)


async def _insert_quiz(document_id: str, topic: str, questions: list) -> str:
    # A fresh engine per call, not database.py's shared AsyncSessionLocal:
    # asyncio.run() (see generate_quiz below) gives this coroutine a
    # brand-new event loop every invocation, but the shared engine's
    # asyncpg connection pool binds connections to whichever loop created
    # them -- reusing it across separate asyncio.run() calls raises
    # "attached to a different loop"/"another operation is in progress".
    # Creating and disposing the engine within this one call's own loop
    # sidesteps that entirely.
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with SessionLocal() as session:
            quiz = Quiz(document_id=document_id, topic=topic, questions=questions)
            session.add(quiz)
            await session.commit()
            await session.refresh(quiz)
            return str(quiz.id)
    finally:
        await engine.dispose()


@celery_app.task(bind=True, max_retries=2, name="generate_quiz")
def generate_quiz(self, user_id, document_id, topic):
    try:
        questions = request_quiz(document_id, topic)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=GENERATE_QUIZ_RETRY_COUNTDOWN)

    try:
        quiz_id = asyncio.run(_insert_quiz(document_id, topic, questions))
    except Exception as exc:
        log.error("generate_quiz_insert_failed", document_id=document_id, error=str(exc))
        return

    try:
        celery_app.send_task("notify_quiz_ready", args=[user_id, quiz_id])
    except Exception as exc:
        log.warning("notify_quiz_ready_dispatch_failed", quiz_id=quiz_id, error=str(exc))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/core-api && pytest tests/test_worker_generate_quiz.py -v`
Expected: PASS.

- [ ] **Step 6: Add the endpoint**

Edit `services/core-api/routes.py`. Add after the existing
`QuizUpdateRequest` class (in the `# ---- Quizzes ----` section):

```python
class GenerateQuizRequest(BaseModel):
    document_id: uuid.UUID
    topic: str
```

Add after the existing `create_quiz` route:

```python
@router.post("/quizzes/generate", status_code=202)
async def generate_quiz_request(
    request: GenerateQuizRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = await _get_owned_document(request.document_id, user, db)
    if document.status != "ready":
        raise HTTPException(status_code=409, detail="Document not ready for quiz generation")
    task = celery_app.send_task(
        "generate_quiz",
        args=[str(user.id), str(request.document_id), request.topic],
    )
    return {"job_id": task.id}
```

- [ ] **Step 7: Write and run a test for the endpoint's guards**

Append to `services/core-api/tests/test_document_upload_route.py`
(reuses its existing `auth`/imports):

```python
@pytest.mark.asyncio
async def test_generate_quiz_409s_when_document_not_ready():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/documents", json={"title": "Not Ready Doc", "status": "uploaded"}, headers=auth(ALICE_ID)
        )
        document = create_response.json()

        generate_response = await client.post(
            "/quizzes/generate",
            json={"document_id": document["id"], "topic": "Chapter 1"},
            headers=auth(ALICE_ID),
        )

        assert generate_response.status_code == 409


@pytest.mark.asyncio
async def test_generate_quiz_404s_on_other_users_document():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        create_response = await client.post(
            "/documents", json={"title": "Alice's Ready Doc", "status": "ready"}, headers=auth(ALICE_ID)
        )
        document = create_response.json()

        generate_response = await client.post(
            "/quizzes/generate",
            json={"document_id": document["id"], "topic": "Chapter 1"},
            headers=auth(BOB_ID),
        )

        assert generate_response.status_code == 404
```

Run: `cd services/core-api && pytest tests/test_document_upload_route.py -v`
Expected: all tests (upload + generate-quiz guards) PASS.

- [ ] **Step 8: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/core-api/agentic_client.py services/core-api/routes.py services/core-api/worker.py services/core-api/tests/test_worker_generate_quiz.py services/core-api/tests/test_document_upload_route.py
git commit -m "feat(core-api): add POST /quizzes/generate + async generate_quiz task

Ownership-checked, 409s if the document isn't ready. Task calls the
agentic service (max_retries=2, retry wraps only the HTTP call -- a DB
insert failure logs and stops rather than re-running the expensive LLM
call), inserts the quiz, and reuses the existing notify_quiz_ready task."
```

---

### Task 4: Retry integration test for generate_quiz

**Files:**
- Create: `services/core-api/tests/test_worker_generate_quiz_retry.py`

**Interfaces:**
- Consumes: `celery_app` (Task 3), the `"generate_quiz"` task name (Task
  3), `GENERATE_QUIZ_RETRY_COUNTDOWN` env var (Task 3).

This mirrors `test_worker_retry.py`'s existing pattern exactly (see
`services/core-api/tests/test_worker_retry.py`): a dedicated Celery worker
process, pointed at an unreachable target with a short retry countdown, so
the full retry cycle runs in seconds. Because `generate_quiz`'s first step
(the agentic HTTP call) is where this test forces failure, no real
document row is needed — the task never reaches the DB insert.

- [ ] **Step 1: Write the test**

Create `services/core-api/tests/test_worker_generate_quiz_retry.py`:

```python
import time
from celery.result import AsyncResult
from worker import celery_app

ALICE_ID = "11111111-1111-1111-1111-111111111111"
FAKE_DOCUMENT_ID = "33333333-3333-3333-3333-333333333333"


def test_generate_quiz_retries_then_fails():
    task = celery_app.send_task(
        "generate_quiz",
        args=[ALICE_ID, FAKE_DOCUMENT_ID, "Chapter 1"],
        queue="generate_quiz_retry_test",
    )
    result = AsyncResult(task.id, app=celery_app)

    start = time.monotonic()
    timeout = 15
    while not result.ready() and time.monotonic() - start < timeout:
        time.sleep(0.2)
    elapsed = time.monotonic() - start

    assert result.ready(), f"task did not finish within {timeout}s (state={result.state})"
    assert result.state == "FAILURE"
    # 2 retries at ~1s each (GENERATE_QUIZ_RETRY_COUNTDOWN=1 in this
    # test's worker env) -- proves the retry loop ran more than once,
    # not that it failed immediately on the first attempt.
    assert elapsed >= 1.5, f"expected at least ~2s of retries, only took {elapsed:.1f}s"
```

- [ ] **Step 2: Start a dedicated worker for this test and run it**

`--pool=solo` keeps the worker single-process, so `kill $WORKER_PID`
actually stops it (the default prefork pool forks children it wouldn't
reach). `-Q generate_quiz_retry_test` means this worker only consumes
from that dedicated queue — the docker-compose `worker` container
(default queue, reachable agentic service) never competes for this task.

```bash
cd services/core-api
source /tmp/edumind_venv/bin/activate
export DATABASE_URL="postgresql+asyncpg://edumind:edumind@localhost:5432/edumind"
export REDIS_URL="redis://localhost:6379/0"
export AGENTIC_SERVICE_URL="http://localhost:59998"
export GENERATE_QUIZ_RETRY_COUNTDOWN="1"
celery -A worker worker --loglevel=info --pool=solo -Q generate_quiz_retry_test &
WORKER_PID=$!
sleep 3
python -m pytest tests/test_worker_generate_quiz_retry.py -v
TEST_EXIT=$?
kill $WORKER_PID
wait $WORKER_PID 2>/dev/null
exit $TEST_EXIT
```

Expected: `test_generate_quiz_retries_then_fails PASSED`. The worker's own
log output should show two `Retry` log lines before it finally logs
failure — confirms `max_retries=2` was honored.

- [ ] **Step 3: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/core-api/tests/test_worker_generate_quiz_retry.py
git commit -m "test(core-api): add retry integration test for generate_quiz

Runs against a real worker process with a short retry countdown
(GENERATE_QUIZ_RETRY_COUNTDOWN=1) and an unreachable agentic target, so
the full 2-retry cycle is exercised in seconds instead of minutes."
```

---

### Task 5: Full-stack manual verification

**Files:** none (verification only).

**Interfaces:**
- Consumes: everything from Tasks 1-4.

- [ ] **Step 1: Rebuild and restart affected containers**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
docker-compose up -d --build core-api worker agentic
sleep 10
curl -s http://localhost:8000/health
curl -s http://localhost:8002/health
```

Expected: both return `{"status":"ok"}`.

- [ ] **Step 2: Create a document and upload real content**

```bash
ALICE_ID="11111111-1111-1111-1111-111111111111"
DOC_ID=$(curl -s -X POST http://localhost:8000/documents \
  -H "X-User-Id: $ALICE_ID" -H "Content-Type: application/json" \
  -d '{"title": "E2E Test Doc", "status": "uploaded"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
echo "DOC_ID=$DOC_ID"

curl -s -X POST "http://localhost:8000/documents/$DOC_ID/upload" \
  -H "X-User-Id: $ALICE_ID" \
  -F "file=@services/agentic/uploads/test_curriculum.pdf"
```

Expected: `200`, `"status":"ready"`.

- [ ] **Step 3: Request quiz generation**

```bash
JOB_ID=$(curl -s -X POST http://localhost:8000/quizzes/generate \
  -H "X-User-Id: $ALICE_ID" -H "Content-Type: application/json" \
  -d "{\"document_id\": \"$DOC_ID\", \"topic\": \"machine learning\"}" | python3 -c "import sys,json; print(json.load(sys.stdin)['job_id'])")
echo "JOB_ID=$JOB_ID"
```

Expected: `202`, a `job_id` returned. Requires a real `ANTHROPIC_API_KEY`
configured for the `agentic` service (per `services/agentic/.env`) — this
step makes a real Claude call.

- [ ] **Step 4: Confirm the quiz was created and a notification fired**

```bash
sleep 15
curl -s http://localhost:8000/quizzes -H "X-User-Id: $ALICE_ID"
curl -s "http://localhost:5000/notifications?user_id=$ALICE_ID" -H "X-User-Id: $ALICE_ID"
```

Expected: the quizzes list includes a quiz with `document_id == $DOC_ID`
and `topic == "machine learning"` with non-empty `questions`; the
notifications list includes an entry referencing that quiz's id.

- [ ] **Step 5: Confirm cross-user 404s hold on the new endpoints**

```bash
BOB_ID="22222222-2222-2222-2222-222222222222"
curl -s -o /dev/null -w "%{http_code}\n" -X POST "http://localhost:8000/documents/$DOC_ID/upload" \
  -H "X-User-Id: $BOB_ID" -F "file=@services/agentic/uploads/test_curriculum.pdf"
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8000/quizzes/generate \
  -H "X-User-Id: $BOB_ID" -H "Content-Type: application/json" \
  -d "{\"document_id\": \"$DOC_ID\", \"topic\": \"machine learning\"}"
```

Expected: both print `404`.

No commit for this task — verification only. If any step fails, fix the
underlying task and re-run from Step 1.
