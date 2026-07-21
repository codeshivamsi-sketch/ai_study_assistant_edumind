# Phase B4 — Connect core-api to the agentic service — design

## Context

Goal: quiz generation via the agentic service, async end-to-end. A client
should be able to request a quiz for one of their documents by topic, and
have `core-api` call the agentic service's LLM/retrieval pipeline in the
background, insert the resulting quiz, and notify the client via the
existing Phase B3 notifications pipeline — without blocking the request.

The originally proposed plan assumed `POST /quizzes/generate { document_id,
topic }` could ask the agentic service to generate a quiz "about that
document." Inspecting the actual agentic service (`services/agentic/`)
surfaced a load-bearing gap: **it has no concept of a document at all.**

- `core-api`'s `documents` table (`models.py`) is pure metadata (`id`,
  `user_id`, `title`, `status`) — it has never stored or received file
  bytes, and there is no upload endpoint.
- The agentic service's only ingestion path, `POST /upload`, writes chunks
  into **one single global Chroma collection** with ids `str(0..N)` reset
  on every upload — a second PDF's chunks collide with the first's.
- `POST /query` and `POST /agent` both take only a free-text `question`;
  retrieval (`get_searched_chunks_from_chroma`) always searches the entire
  global collection, never scoped to a document or user.
- `/agent`'s quiz path is a human-in-the-loop flow (pauses at a LangGraph
  interrupt awaiting `POST /evaluate`), not a single-shot "give me
  questions and be done" call.

Two decisions resolve this, confirmed with the user:

1. **Add document scoping to the agentic service** (chunks tagged and
   filtered by `document_id`), rather than accepting cross-tenant/global
   retrieval as a permanent limitation.
2. **Add a real upload endpoint to core-api** (`POST
   /documents/{id}/upload`) that forwards the file into the agentic
   service, tagged with `document_id` — otherwise there is no way to get a
   document's content into the agentic service without bypassing core-api
   entirely.

## Agentic service changes (`services/agentic`)

**`core/model.py`** — `AgentRequest` and `QueryRequest` gain
`document_id: Optional[str] = None`. Default `None` preserves today's
global-search behavior for existing callers that never pass one (the MCP
server, the eval harness).

**`core/ingest.py`** — `store_in_chroma(chunks, embeddings,
document_id=None)`:
- If `document_id` given: ids become `f"{document_id}-{i}"`, each chunk
  gets `metadata={"document_id": document_id}`.
- If omitted: unchanged (`f"{i}"` ids, no metadata) — today's behavior.

**`core/query.py`** — `get_searched_chunks_from_chroma(embedding,
document_id=None)`: adds `where={"document_id": document_id}` to the
Chroma query when given; omitted means today's unfiltered global search.

**`agents/agents.py`** — `EduMindState` gains `document_id: str`;
`retrieval_node` reads it from state and threads it into
`get_searched_chunks_from_chroma`.

**`api/main.py`**:
- `/upload` gains `document_id: Optional[str] = Form(None)`, passed to
  `store_in_chroma`.
- `/agent` passes `request.document_id` into the graph's initial state.

**Explicitly not changed / deferred:**
- Neo4j knowledge graph stays global — no `document_id` property on nodes
  or relationships, no Cypher filtering. A knowledge graph linking
  concepts *across* documents is arguably correct behavior, not a bug; and
  scoping it is materially more work than scoping Chroma. `related_concepts`
  in `/agent` responses may include concepts from other documents.
- Re-uploading the same `document_id` a second time is unsupported — Chroma
  will raise on the duplicate ids (no upsert/replace logic). Acceptable for
  this phase; would need real handling before supporting document
  replacement/re-ingestion.

## core-api changes

### New: `POST /documents/{document_id}/upload`

Multipart file upload. Requires `python-multipart` added to
`services/core-api/requirements.txt` (FastAPI's `UploadFile` parsing
dependency; already present in the agentic service's requirements).

- Ownership check via the existing `_get_owned_document` helper — 404 if
  not the caller's document, matching every other endpoint's pattern.
- Sets `document.status = "processing"`, commits.
- Forwards the file to the agentic service via `httpx.AsyncClient`
  (`AGENTIC_SERVICE_URL`, already wired into `docker-compose.yml` since
  Phase B2's agentic consolidation, unused until now) as multipart form
  data, passing `document_id`.
- On success (`200` from agentic): `status = "ready"`, commit, return the
  document.
- On failure (exception, or non-`200`): `status = "failed"`, commit, raise
  `HTTPException(502)`.

**Deliberately not Celery/async.** Test PDFs in this project are small
(~13KB) and `httpx.AsyncClient`'s `await` doesn't block the event loop —
true async I/O, not a blocking call needing thread-offload. Shipping raw
PDF bytes through Redis/Celery message payloads is the wrong tool for this
size of data. Only quiz *generation* (the slow, LLM-bound step) needs to be
async, per the original ask. Known ceiling: large PDFs or a slow agentic
pipeline would make this request slow for the caller — revisit with a
Celery-based ingestion task if that becomes real.

### `POST /quizzes/generate` (as originally specified, plus one guard)

```
{ document_id, topic } → 202 { job_id }
```

- Ownership check via `_get_owned_document` (404 pattern, unchanged).
- **New guard**: `409` if `document.status != "ready"` — otherwise the
  task would run against zero retrieved chunks for that document with no
  clear error, since the document was never ingested (or ingestion
  failed).
- `celery_app.send_task("generate_quiz", args=[str(user.id),
  str(document_id), topic])`, returns `202 {"job_id": task.id}`.

### `generate_quiz` Celery task (`worker.py`)

```
generate_quiz(user_id, document_id, topic)
```

1. `httpx.post(f"{AGENTIC_SERVICE_URL}/agent", json={"question": f"Quiz me
   on {topic}", "document_id": document_id}, timeout=60)`. On failure:
   `self.retry(exc=exc, countdown=GENERATE_QUIZ_RETRY_COUNTDOWN)`,
   `max_retries=2` (env-overridable, mirroring `NOTIFY_QUIZ_READY_RETRY_COUNTDOWN`'s
   pattern) — fewer than `notify_quiz_ready`'s 3, since these are slow,
   expensive LLM calls, not a cheap gRPC ping.
2. On a successful response: insert the `Quiz` row (`document_id`, `topic`,
   `questions=response.json()["quiz_questions"]`). **This step is not
   wrapped in the retry** — a DB hiccup after a successful (expensive) LLM
   call should log and stop, not re-trigger the LLM call to satisfy a
   retry. Matches the plan's stated final-failure behavior: log, no quiz
   row.
3. On successful insert: `celery_app.send_task("notify_quiz_ready",
   args=[user_id, str(quiz.id)])`, reusing Phase B3's existing task
   unchanged. Dispatch failure here is best-effort/logged, exactly like
   the existing `create_quiz` route — never fails the already-completed
   quiz creation.

**Bridging sync Celery to async SQLAlchemy:** `database.py` only has an
async engine (`AsyncSessionLocal`) — the existing `notify_quiz_ready` task
never touched Postgres, so this hasn't come up before. `generate_quiz`
wraps its DB insert in a small `async def` helper and drives it with
`asyncio.run(...)` — a standard, dependency-free bridging pattern. No new
engine, no new dependency.

**Client completion signal:** once `notify_quiz_ready` fires, the existing
Phase B3 notifications pipeline (BullMQ → `GET /notifications`) already
tells the client a quiz is ready — no new job-status polling endpoint
needed. `job_id` from the `202` response is returned for traceability but
nothing polls it in this phase.

## Unchanged

- `POST /quizzes` (manual questions) — untouched.
- `notify_quiz_ready` task — untouched, reused as-is.
- Ownership/404 invariants — unchanged, extended to the new endpoints via
  the existing `_get_owned_document` helper.

## Tests

- **Happy-path chain test** (mirrors `test_worker.py`'s existing style —
  plain sync test function, `.apply()`, `monkeypatch.setattr`): mock
  `worker.httpx.post` to return a canned `quiz_questions` payload, mock
  `worker.celery_app.send_task` to capture the `notify_quiz_ready`
  dispatch, assert a `Quiz` row was inserted with the expected
  `document_id`/`topic`/`questions` and that `notify_quiz_ready` was
  dispatched with the right args. Test document setup/teardown and the
  post-task DB verification both go through small `asyncio.run(...)`-wrapped
  helpers (sequential, not nested inside an already-running loop — the
  test function itself stays a plain `def`, not `async def`, exactly like
  `test_worker.py` already does, avoiding a `RuntimeError` from calling
  `asyncio.run()` inside pytest-asyncio's own running loop).
- **Retry test** (mirrors `test_worker_retry.py`'s existing pattern):
  dedicated queue (`generate_quiz_retry_test`), `AGENTIC_SERVICE_URL`
  pointed at an unreachable host for a dedicated worker process,
  `GENERATE_QUIZ_RETRY_COUNTDOWN=1`, assert `FAILURE` after retries with an
  elapsed-time lower bound tight enough to distinguish 2 retries from
  fewer (matching the post-review fix applied to Phase B3's equivalent
  test).
- Manual E2E (not automated): needs a real `ANTHROPIC_API_KEY` — upload a
  PDF via the new endpoint, `POST /quizzes/generate`, confirm a quiz
  appears and a notification fires.

## What's explicitly out of scope

- Document replacement/re-ingestion (re-uploading the same `document_id`).
- Neo4j per-document scoping.
- Job-status polling for `POST /quizzes/generate`'s `job_id`.
- Making the upload endpoint itself async/Celery-based.
- Any change to `/evaluate` or the human-in-the-loop quiz-answering flow —
  this phase only uses `/agent`'s quiz-generation output, never calls
  `/evaluate`.
