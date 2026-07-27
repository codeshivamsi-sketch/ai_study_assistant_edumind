# Async Chat Pipeline (agentic RQ worker + core-api callback) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chat message answering fully async end-to-end. `core-api` hands
the question to `agentic` and returns immediately; `agentic` processes it on
a new RQ worker (its first queue) and calls `core-api` back over plain HTTP
when the LLM work finishes. Direct-from-client quiz creation is removed —
quizzes now only originate from chat intent detection.

**Architecture:** `POST /chats/{chat_id}/messages` inserts the user message,
fires a fast HTTP call to agentic's `/agent` (now enqueue-and-ack, 202), and
returns 202 itself. Agentic's RQ job runs today's LangGraph invocation
unchanged, then POSTs the raw result to a new `POST /internal/chat-answers`
on core-api, which extracts the answer (or JSON-serializes the fallback,
exactly like today's `ask_question`), inserts the assistant `Message`, and —
if the LLM classified the message as a quiz — inserts a `Quiz` row directly.
That handler also dispatches the existing `notify_quiz_ready` Celery task,
generalized to carry `chat_id`/`message_id` as an alternative to `quiz_id` so
both quiz-ready and chat-answer notifications flow through the one existing
gRPC → BullMQ → Prisma pipeline.

**Tech Stack:** FastAPI, RQ (`rq` + `redis` packages, agentic's first queue),
Celery (unchanged, core-api), BullMQ (unchanged, notifications), gRPC/protobuf
(generalized), Alembic (unchanged — no core-api schema change), Prisma
(migration for `notifications`).

## Global Constraints

- No gRPC infrastructure added to agentic — the agentic→core-api callback is
  plain HTTP, reusing each service's existing FastAPI server.
- Redis logical DB assignment across the three queueing systems on one Redis
  instance: DB 0 = Celery (core-api, existing, unchanged), DB 1 = BullMQ
  (notifications, existing, unchanged), **DB 2 = RQ (agentic, new)**.
- `POST /quiz_attempts` stays completely untouched — synchronous, client-driven,
  no queue involved, not touched by any task below.
- RQ (not Celery) for agentic's new worker — this is agentic's first queue,
  no existing pattern to match there.
- Ownership checks return 404, never 403 (project-wide invariant) — unaffected
  by this plan except where noted; `/internal/chat-answers` is an
  internal-only endpoint with no `X-User-Id` auth (see Resolved Decisions).

## Resolved decisions (read before objecting mid-implementation)

1. **`notify_quiz_ready` keeps its name** (Celery task, gRPC RPC, BullMQ queue
   constant) rather than being renamed to something generic. The brief asked
   to "generalize the notify chain," not rename identifiers — renaming would
   ripple into generated gRPC stubs, the BullMQ queue name, and existing
   tests (`test_worker_retry.py`) for no functional gain. Instead, `quiz_id`
   becomes **optional** everywhere (proto, Prisma, Python, TS) and `chat_id`/
   `message_id` are added as new optional fields alongside it. A notification
   row's subject is inferred from which of `quiz_id` vs `chat_id` is set —
   no new discriminator column.
2. **`POST /chats/{chat_id}/messages`'s response contract changes**: today it's
   synchronous `200 {user_message, assistant_message}`; it becomes
   `202 {user_message}`. No polling/job-id endpoint is added (matches the
   existing `/quizzes/generate` precedent of no polling machinery) — the
   client sees the assistant reply later via `GET /chats/{chat_id}/messages`.
3. **A quiz auto-created from chat intent uses the triggering message's
   content, verbatim, as `topic`** — chat has no separate "topic" input, unlike
   the old `POST /quizzes/generate`.
4. **`/internal/chat-answers` has no auth** beyond docker-network trust,
   matching agentic's own existing unauthenticated endpoints (`/upload`,
   `/agent`) — it derives `user_id` by loading the `Chat` row via `chat_id`
   in the payload, not from a header.
5. **No retry on the agentic→core-api callback POST** this phase — if it
   fails, the assistant message is simply never created; the user message row
   still exists. Explicitly out of scope, matching how the original chat
   plan deferred async/polling machinery. `run_agent_job` still logs (prints)
   the failure for operator visibility.
6. **`/agent` becomes async-only, unconditionally** (no sync fallback) —
   its only other direct caller, `services/agentic/mcp/server.py`, already
   calls the already-removed `/query` endpoint elsewhere in the same file
   (an existing, uncommitted, out-of-scope breakage from a prior session) —
   it is not an actively-relied-upon caller. Not fixed here.
7. **New Redis DB 2 URL env var name**: `AGENTIC_REDIS_URL`, default
   `redis://localhost:6379/2`, read by both the FastAPI process (to enqueue)
   and the new worker process (to dequeue) — but the FastAPI process enqueues
   by **string reference** (`"core.jobs.run_agent_job"`), not by importing the
   job function, so it never imports `agents.agents` (and its module-level
   Anthropic client + SQLite checkpoint connection) just to enqueue.
8. **Notification FK behavior for the two new columns**: `chat_id`/`message_id`
   get `ON DELETE CASCADE` FKs into `chats`/`messages`, matching the existing
   hand-added `user_id → users` FK's `CASCADE` behavior on this table.

---

### Task 1: Generalize the notify pipeline (proto, Prisma, grpc_client.py, worker.py)

**Files:**
- Modify: `proto/notifications.proto`
- Modify: `services/notifications/prisma/schema.prisma`
- Create: `services/notifications/prisma/migrations/20260726000000_generalize_notifications/migration.sql`
- Modify: `services/notifications/src/grpc/server.ts`
- Modify: `services/notifications/src/queue.ts`
- Modify: `services/notifications/src/jobs/notifyQuizReady.ts`
- Modify: `services/core-api/grpc_client.py`
- Modify: `services/core-api/worker.py`
- Regenerate: `services/core-api/notifications_pb2.py`, `services/core-api/notifications_pb2_grpc.py` (via `make proto`)

**Interfaces:**
- Produces: `grpc_client.notify_quiz_ready(user_id, quiz_id=None, chat_id=None, message_id=None) -> None` and Celery task `notify_quiz_ready(self, user_id, quiz_id=None, chat_id=None, message_id=None)` — Task 3 dispatches this with `chat_id`/`message_id` set and `quiz_id=None` (or `quiz_id` set, for the quiz-intent case).

- [ ] **Step 1: Edit the proto**

```protobuf
syntax = "proto3";

package notifications;

service NotificationService {
  rpc NotifyQuizReady (NotifyQuizReadyRequest) returns (NotifyQuizReadyResponse);
}

message NotifyQuizReadyRequest {
  string user_id = 1;
  optional string quiz_id = 2;
  optional string chat_id = 3;
  optional string message_id = 4;
}

message NotifyQuizReadyResponse {
  bool accepted = 1;
}
```

Overwrite `proto/notifications.proto` with this content. (`services/notifications/proto/notifications.proto` is a gitignored build copy — `npm run copy-proto` refreshes it at build time; don't hand-edit it.)

- [ ] **Step 2: Regenerate core-api's Python gRPC stubs**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
make proto
```
Expected: `services/core-api/notifications_pb2.py` and `notifications_pb2_grpc.py` are rewritten with `quiz_id`/`chat_id`/`message_id` all present and `optional`-tagged (check for a `oneof _quiz_id` / `_chat_id` / `_message_id` wrapper in the rewritten `notifications_pb2.py` — proto3 `optional` compiles to a single-field `oneof` for presence-tracking).

- [ ] **Step 3: Update `grpc_client.py`**

Replace the whole file:

```python
import os
import grpc
import notifications_pb2
import notifications_pb2_grpc

NOTIFICATIONS_GRPC_URL = os.getenv("NOTIFICATIONS_GRPC_URL", "localhost:5001")


def notify_quiz_ready(
    user_id: str,
    quiz_id: str | None = None,
    chat_id: str | None = None,
    message_id: str | None = None,
) -> None:
    request_kwargs = {"user_id": user_id}
    if quiz_id:
        request_kwargs["quiz_id"] = quiz_id
    if chat_id:
        request_kwargs["chat_id"] = chat_id
    if message_id:
        request_kwargs["message_id"] = message_id

    with grpc.insecure_channel(NOTIFICATIONS_GRPC_URL) as channel:
        stub = notifications_pb2_grpc.NotificationServiceStub(channel)
        stub.NotifyQuizReady(
            notifications_pb2.NotifyQuizReadyRequest(**request_kwargs),
            timeout=5,
        )
```

- [ ] **Step 4: Update `worker.py`'s `notify_quiz_ready` task**

In `services/core-api/worker.py`, replace:

```python
@celery_app.task(bind=True, max_retries=3, name="notify_quiz_ready")
def notify_quiz_ready(self, user_id, quiz_id):
    try:
        send_grpc_notification(user_id, quiz_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=RETRY_COUNTDOWN)
```

with:

```python
@celery_app.task(bind=True, max_retries=3, name="notify_quiz_ready")
def notify_quiz_ready(self, user_id, quiz_id=None, chat_id=None, message_id=None):
    try:
        send_grpc_notification(user_id, quiz_id=quiz_id, chat_id=chat_id, message_id=message_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=RETRY_COUNTDOWN)
```

This keeps `celery_app.send_task("notify_quiz_ready", args=[user_id, quiz_id])`
(the exact call `tests/test_worker_retry.py` and today's `create_quiz`/
`generate_quiz` use) working unchanged — `quiz_id` is still the second
positional arg, just now defaulted.

- [ ] **Step 5: Verify the existing retry test still passes unchanged**

```bash
cd services/core-api
export DATABASE_URL="postgresql+asyncpg://edumind:edumind@localhost:5432/edumind"
export REDIS_URL="redis://localhost:6379/0"
export NOTIFICATIONS_GRPC_URL="localhost:59999"
export NOTIFY_QUIZ_READY_RETRY_COUNTDOWN="1"
./.venv/bin/celery -A worker worker --loglevel=info --pool=solo -Q notify_quiz_ready_retry_test &
WORKER_PID=$!
sleep 3
./.venv/bin/python -m pytest tests/test_worker_retry.py -v
TEST_EXIT=$?
kill $WORKER_PID
wait $WORKER_PID 2>/dev/null
exit $TEST_EXIT
```
Expected: `test_notify_quiz_ready_retries_then_fails PASSED` — unchanged from
before this task (proves the new optional kwargs didn't break the existing
positional call shape).

- [ ] **Step 6: Add a unit test for the new optional fields**

Create `services/core-api/tests/test_grpc_client.py`:

```python
import notifications_pb2


def test_notify_quiz_ready_request_accepts_chat_fields_without_quiz_id():
    request = notifications_pb2.NotifyQuizReadyRequest(
        user_id="11111111-1111-1111-1111-111111111111",
        chat_id="22222222-2222-2222-2222-222222222222",
        message_id="33333333-3333-3333-3333-333333333333",
    )
    assert request.user_id == "11111111-1111-1111-1111-111111111111"
    assert request.chat_id == "22222222-2222-2222-2222-222222222222"
    assert request.message_id == "33333333-3333-3333-3333-333333333333"
    assert not request.HasField("quiz_id")


def test_notify_quiz_ready_request_still_accepts_quiz_id_only():
    request = notifications_pb2.NotifyQuizReadyRequest(
        user_id="11111111-1111-1111-1111-111111111111",
        quiz_id="44444444-4444-4444-4444-444444444444",
    )
    assert request.HasField("quiz_id")
    assert not request.HasField("chat_id")
```

Run: `cd services/core-api && ./.venv/bin/python -m pytest tests/test_grpc_client.py -v`
Expected: both PASS (proves the regenerated stub actually has presence-tracking
`optional` fields, not the plain proto3 default-value semantics that would
make `HasField` raise).

- [ ] **Step 7: Prisma schema + migration**

Edit `services/notifications/prisma/schema.prisma`'s `Notification` model:

```prisma
model Notification {
  id         String   @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  user_id    String   @db.Uuid
  quiz_id    String?  @db.Uuid
  chat_id    String?  @db.Uuid
  message_id String?  @db.Uuid
  message    String
  read       Boolean  @default(false)
  created_at DateTime @default(now())

  @@index([user_id])
  @@map("notifications")
}
```

Create `services/notifications/prisma/migrations/20260726000000_generalize_notifications/migration.sql`:

```sql
-- AlterTable: quiz_id becomes optional (chat-answer notifications have none)
ALTER TABLE "notifications" ALTER COLUMN "quiz_id" DROP NOT NULL;

-- AlterTable: new optional columns for chat-answer notifications
ALTER TABLE "notifications" ADD COLUMN "chat_id" UUID;
ALTER TABLE "notifications" ADD COLUMN "message_id" UUID;

-- AddForeignKey (hand-written, same pattern as the existing user_id FK —
-- chats/messages are core-api's Alembic tables, not Prisma's)
ALTER TABLE "notifications" ADD CONSTRAINT "notifications_chat_id_fkey" FOREIGN KEY ("chat_id") REFERENCES "chats"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "notifications" ADD CONSTRAINT "notifications_message_id_fkey" FOREIGN KEY ("message_id") REFERENCES "messages"("id") ON DELETE CASCADE ON UPDATE CASCADE;
```

Do **not** run `prisma migrate dev` against the shared `edumind` database
(schema.prisma's own warning). Apply with:
```bash
cd services/notifications
npx prisma migrate deploy
```
Expected: `Applying migration 20260726000000_generalize_notifications` then
success.

- [ ] **Step 8: Update the TS gRPC handler, queue, and job**

`services/notifications/src/grpc/server.ts` — replace the `notifyQuizReady`
function body:

```typescript
interface NotifyQuizReadyRequest {
  user_id: string;
  quiz_id?: string;
  chat_id?: string;
  message_id?: string;
}

interface NotifyQuizReadyResponse {
  accepted: boolean;
}

async function notifyQuizReady(
  call: grpc.ServerUnaryCall<NotifyQuizReadyRequest, NotifyQuizReadyResponse>,
  callback: grpc.sendUnaryData<NotifyQuizReadyResponse>
) {
  const { user_id, quiz_id, chat_id, message_id } = call.request;
  try {
    await enqueueNotifyQuizReady({
      user_id,
      quiz_id: quiz_id || null,
      chat_id: chat_id || null,
      message_id: message_id || null,
      message: quiz_id ? "Your quiz is ready!" : "You have a new chat answer!",
    });
    callback(null, { accepted: true });
  } catch (err) {
    logger.error(err, "notify_quiz_ready_grpc_failed");
    callback({ code: grpc.status.INTERNAL, message: "Failed to enqueue notification" });
  }
}
```

`services/notifications/src/queue.ts` — replace the payload interface:

```typescript
export interface NotifyQuizReadyPayload {
  user_id: string;
  quiz_id: string | null;
  chat_id: string | null;
  message_id: string | null;
  message: string;
}
```

`services/notifications/src/jobs/notifyQuizReady.ts` — replace `processNotifyQuizReady`:

```typescript
export async function processNotifyQuizReady(job: Job<NotifyQuizReadyPayload>) {
  const { user_id, quiz_id, chat_id, message_id, message } = job.data;
  await prisma.notification.create({
    data: { user_id, quiz_id, chat_id, message_id, message },
  });
}
```

- [ ] **Step 9: Build and run the notifications test suite**

```bash
cd services/notifications
npm run build
npm test
```
Expected: build succeeds (TS types match the updated Prisma client), existing
tests green.

- [ ] **Step 10: Commit**

```bash
git add proto/notifications.proto services/notifications/prisma/schema.prisma \
  services/notifications/prisma/migrations/20260726000000_generalize_notifications \
  services/notifications/src/grpc/server.ts services/notifications/src/queue.ts \
  services/notifications/src/jobs/notifyQuizReady.ts \
  services/core-api/grpc_client.py services/core-api/worker.py \
  services/core-api/notifications_pb2.py services/core-api/notifications_pb2_grpc.py \
  services/core-api/tests/test_grpc_client.py
git commit -m "feat: generalize notify_quiz_ready to carry chat_id/message_id"
```

---

### Task 2: Agentic RQ infrastructure + `/agent` becomes enqueue-and-ack

**Files:**
- Modify: `services/agentic/requirements.txt`
- Create: `services/agentic/core/queue_client.py`
- Create: `services/agentic/core/jobs.py`
- Modify: `services/agentic/api/main.py`
- Modify: `services/agentic/core/model.py`
- Modify: `docker-compose.yml`
- Create: `services/agentic/tests/test_jobs.py` (new — this service has no
  existing test directory; check first: `find services/agentic -iname "test*"`
  before assuming none exist)

**Interfaces:**
- Produces: `core.queue_client.job_queue` (an `rq.Queue`), `core.jobs.run_agent_job(question, document_id, chat_id, message_id) -> None` — Task 3 doesn't call this directly (it's invoked by the RQ worker process), but Task 3's callback endpoint receives exactly the payload shape this function POSTs.

- [ ] **Step 1: Add dependencies**

Append to `services/agentic/requirements.txt`:
```
rq
redis
httpx
```

- [ ] **Step 2: Redis connection + queue module**

Create `services/agentic/core/queue_client.py`:

```python
import os
from redis import Redis
from rq import Queue

AGENTIC_REDIS_URL = os.getenv("AGENTIC_REDIS_URL", "redis://localhost:6379/2")
redis_conn = Redis.from_url(AGENTIC_REDIS_URL)
job_queue = Queue("agent_jobs", connection=redis_conn)
```

- [ ] **Step 3: The job function**

Create `services/agentic/core/jobs.py`:

```python
import os
import uuid
import httpx
from agents.agents import agent

CORE_API_CALLBACK_URL = os.getenv("CORE_API_CALLBACK_URL", "http://localhost:8000")


def run_agent_job(question: str, document_id: str, chat_id: str, message_id: str) -> None:
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"question": question, "document_id": document_id}, config=config)

    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "result": {**result, "thread_id": thread_id},
    }
    try:
        response = httpx.post(f"{CORE_API_CALLBACK_URL}/internal/chat-answers", json=payload, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        print(f"chat_answer_callback_failed chat_id={chat_id} message_id={message_id} error={exc}")
```

This is the exact same `agent.invoke(...)` call `agent_endpoint` makes today —
moved verbatim, just invoked from an RQ job instead of inline in the HTTP
handler. Per Resolved Decision 5, callback failures are logged (`print`,
matching this file's existing style elsewhere in `core/ingest.py`/`core/graph.py`)
and swallowed, not retried.

- [ ] **Step 4: `AgentRequest` gains `chat_id`/`message_id`**

In `services/agentic/core/model.py`, replace:

```python
class AgentRequest(BaseModel):
    question: str
    document_id: Optional[str] = None
```

with:

```python
class AgentRequest(BaseModel):
    question: str
    document_id: Optional[str] = None
    chat_id: Optional[str] = None
    message_id: Optional[str] = None
```

- [ ] **Step 5: `/agent` becomes enqueue-and-ack**

In `services/agentic/api/main.py`:
- Add `HTTPException` to the `fastapi` import: `from fastapi import FastAPI, UploadFile, File, Form, HTTPException`
- Add `from core.queue_client import job_queue` to the imports
- Replace `agent_endpoint`:

```python
@app.post("/agent", status_code=202)
def agent_endpoint(request: AgentRequest):
    if not request.chat_id or not request.message_id:
        raise HTTPException(status_code=400, detail="chat_id and message_id are required")
    job_queue.enqueue(
        "core.jobs.run_agent_job",
        request.question,
        request.document_id,
        request.chat_id,
        request.message_id,
    )
    return {"accepted": True}
```

`job_queue.enqueue` is called with the job function as a **string reference**
(`"core.jobs.run_agent_job"`), not an imported function object — this is
deliberate (Resolved Decision 7): it means `api/main.py`'s own import list
never has to import `core.jobs` (and transitively `agents.agents`, whose
module-level `SqliteSaver(sqlite3.connect("checkpoints.db"))` and Anthropic
client only need to exist in the worker process now that the API process no
longer calls `agent.invoke` itself). `/evaluate` is untouched — it keeps its
existing `from agents.agents import agent, evaluator_node` import and direct
`agent.get_state`/`agent.update_state`/`agent.stream` calls; this task only
changes how `/agent` itself is implemented.

- [ ] **Step 6: Test the job function directly (no real worker needed)**

```bash
find /Users/shivam/Desktop/projects_2/python_backend_refresher/services/agentic -iname "test*" -o -iname "conftest.py" 2>/dev/null
```
If this returns nothing, create `services/agentic/tests/test_jobs.py`
(mirroring core-api's `generate_quiz.apply(...)` pattern of calling the job
function directly rather than running a real worker):

```python
import core.jobs


def test_run_agent_job_posts_result_to_callback(monkeypatch):
    fake_result = {"answer": "Paris is the capital of France.", "intent": "answer"}
    monkeypatch.setattr("core.jobs.agent.invoke", lambda state, config: fake_result)

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json, timeout):
        posted["url"] = url
        posted["json"] = json
        return FakeResponse()

    monkeypatch.setattr("core.jobs.httpx.post", fake_post)

    core.jobs.run_agent_job(
        question="What is the capital of France?",
        document_id="11111111-1111-1111-1111-111111111111",
        chat_id="22222222-2222-2222-2222-222222222222",
        message_id="33333333-3333-3333-3333-333333333333",
    )

    assert posted["url"] == "http://localhost:8000/internal/chat-answers"
    assert posted["json"]["chat_id"] == "22222222-2222-2222-2222-222222222222"
    assert posted["json"]["message_id"] == "33333333-3333-3333-3333-333333333333"
    assert posted["json"]["result"]["answer"] == "Paris is the capital of France."
    assert "thread_id" in posted["json"]["result"]


def test_run_agent_job_swallows_callback_failure(monkeypatch, capsys):
    monkeypatch.setattr("core.jobs.agent.invoke", lambda state, config: {"answer": "x"})

    def failing_post(url, json, timeout):
        raise ConnectionError("core-api unreachable")

    monkeypatch.setattr("core.jobs.httpx.post", failing_post)

    core.jobs.run_agent_job(
        question="q", document_id="d", chat_id="c", message_id="m"
    )  # must not raise

    captured = capsys.readouterr()
    assert "chat_answer_callback_failed" in captured.out
```

Run: `cd services/agentic && python3 -m pytest tests/test_jobs.py -v` (install
`rq`/`redis`/`httpx`/`pytest` into whatever environment agentic uses first if
not already present — check for a `.venv` there the way core-api has one; if
none exists, note this in your report rather than inventing a new venv setup
convention).

Expected: both PASS.

- [ ] **Step 7: `docker-compose.yml` — new `agentic-worker` service + agentic's new env var**

Add `AGENTIC_REDIS_URL: redis://redis:6379/2` to the existing `agentic`
service's `environment:` block, and add this new service right after it:

```yaml
  agentic-worker:
    build: ./services/agentic
    env_file:
      - ./services/agentic/.env
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: password
      AGENTIC_REDIS_URL: redis://redis:6379/2
      CORE_API_CALLBACK_URL: http://core-api:8000
    depends_on:
      neo4j:
        condition: service_healthy
      redis:
        condition: service_started
    volumes:
      - agentic_chroma:/app/chroma_db
      - agentic_checkpoints:/data
      - agentic_uploads:/app/uploads
    command: rq worker --url redis://redis:6379/2 agent_jobs
```

Same volumes as `agentic` itself (`agentic_chroma`, `agentic_checkpoints`,
`agentic_uploads`) — the worker process needs the same Chroma/checkpoint/
uploads state the LangGraph invocation reads.

- [ ] **Step 8: Commit**

```bash
git add services/agentic/requirements.txt services/agentic/core/queue_client.py \
  services/agentic/core/jobs.py services/agentic/core/model.py \
  services/agentic/api/main.py services/agentic/tests/test_jobs.py \
  docker-compose.yml
git commit -m "feat(agentic): add RQ worker, /agent becomes enqueue-and-ack"
```

---

### Task 3: Core-api `POST /internal/chat-answers` callback + `agentic_client.request_answer`

**Files:**
- Modify: `services/core-api/agentic_client.py`
- Modify: `services/core-api/routes.py`
- Create: `services/core-api/tests/test_chat_answers_callback.py`

**Interfaces:**
- Consumes: `celery_app` (existing), `Chat`/`Message`/`Quiz` models (existing),
  the payload shape Task 2's `run_agent_job` POSTs (`{chat_id, message_id,
  result: {...}}`).
- Produces: `agentic_client.request_answer(chat_id, message_id, document_id,
  question) -> None` — Task 4 calls this from the simplified
  `POST /chats/{chat_id}/messages`.

- [ ] **Step 1: Replace `ask_question` and `request_quiz` with `request_answer`**

In `services/core-api/agentic_client.py`, `ask_question` and `request_quiz`
are both dead once this plan lands (their logic moves to Task 3's callback
handler and their only caller is removed in Task 5, respectively) — remove
both now and add the new fire-and-forget dispatch call. Replace the whole
file:

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


async def request_answer(chat_id: str, message_id: str, document_id: str, question: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{AGENTIC_SERVICE_URL}/agent",
            json={
                "question": question,
                "document_id": document_id,
                "chat_id": chat_id,
                "message_id": message_id,
            },
        )
        response.raise_for_status()
```

(`json`/`request_quiz`'s only-needed-there `import json` moves to `routes.py`
in the next step, since that's where the answer-extraction logic now lives.)

- [ ] **Step 2: Add the callback endpoint to `routes.py`**

Add `import json` to the top imports (alongside the existing `uuid` import).
Change the `agentic_client` import line from:
```python
from agentic_client import upload_document, ask_question
```
to:
```python
from agentic_client import upload_document, request_answer
```

Append a new `# ---- Internal callbacks ----` section after the Chats
section (after `create_message` — which Task 4 will have already touched;
if implementing Task 3 before Task 4, append after the last endpoint in the
file):

```python
# ---- Internal callbacks ----

class ChatAnswerCallbackRequest(BaseModel):
    chat_id: uuid.UUID
    message_id: uuid.UUID
    result: dict

def _extract_answer(result: dict) -> str:
    answer = result.get("answer")
    if answer is not None:
        return answer
    return json.dumps({k: v for k, v in result.items() if k not in ("question", "document_id")})

@router.post("/internal/chat-answers")
async def receive_chat_answer(
    request: ChatAnswerCallbackRequest,
    db: AsyncSession = Depends(get_db),
):
    chat = await db.get(Chat, request.chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    answer = _extract_answer(request.result)
    assistant_message = Message(chat_id=request.chat_id, role="assistant", content=answer)
    db.add(assistant_message)

    quiz = None
    if request.result.get("intent") == "quiz":
        quiz = Quiz(
            document_id=chat.document_id,
            topic=request.result.get("question", "Chat quiz"),
            questions=request.result.get("quiz_questions", []),
        )
        db.add(quiz)

    await db.commit()
    await db.refresh(assistant_message)
    if quiz:
        await db.refresh(quiz)

    try:
        celery_app.send_task(
            "notify_quiz_ready",
            args=[str(chat.user_id)],
            kwargs={
                "quiz_id": str(quiz.id) if quiz else None,
                "chat_id": str(request.chat_id),
                "message_id": str(assistant_message.id),
            },
        )
    except Exception as e:
        log.warning("chat_answer_notify_dispatch_failed", chat_id=str(request.chat_id), error=str(e))

    return {"received": True}
```

This endpoint has **no `Depends(get_current_user)`** — per Resolved Decision
4, it's internal-only, and `user_id` for the notify dispatch comes from
`chat.user_id`, not a header.

- [ ] **Step 3: Write the tests**

Create `services/core-api/tests/test_chat_answers_callback.py`:

```python
import pytest
from httpx import AsyncClient, ASGITransport

from main import app

ALICE_ID = "11111111-1111-1111-1111-111111111111"


def auth(user_id: str) -> dict:
    return {"X-User-Id": user_id}


async def create_document(client: AsyncClient, user_id: str, title: str) -> dict:
    response = await client.post("/documents", json={"title": title, "status": "ready"}, headers=auth(user_id))
    assert response.status_code == 200
    return response.json()


async def create_chat(client: AsyncClient, user_id: str, document_id: str) -> dict:
    response = await client.post("/chats", json={"document_id": document_id, "title": "Chat"}, headers=auth(user_id))
    assert response.status_code == 200
    return response.json()


async def create_user_message(client: AsyncClient, chat_id: str, content: str) -> dict:
    # Inserted directly via the DB in these tests rather than through
    # POST /chats/{chat_id}/messages, since that endpoint's own behavior
    # (Task 4) is tested separately — this file tests the callback in
    # isolation given an already-existing user message.
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from database import DATABASE_URL
    from models import Message

    engine = create_async_engine(DATABASE_URL)
    SessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with SessionLocal() as session:
            message = Message(chat_id=chat_id, role="user", content=content)
            session.add(message)
            await session.commit()
            await session.refresh(message)
            return {"id": str(message.id)}
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_callback_inserts_assistant_message_for_answer_intent(monkeypatch):
    dispatched = {}

    def fake_send_task(name, args=None, kwargs=None):
        dispatched["name"] = name
        dispatched["args"] = args
        dispatched["kwargs"] = kwargs

    monkeypatch.setattr("routes.celery_app.send_task", fake_send_task)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Callback doc")
        chat = await create_chat(client, ALICE_ID, document["id"])
        user_message = await create_user_message(client, chat["id"], "What is this about?")

        response = await client.post(
            "/internal/chat-answers",
            json={
                "chat_id": chat["id"],
                "message_id": user_message["id"],
                "result": {"intent": "answer", "answer": "This document is about photosynthesis."},
            },
        )
        assert response.status_code == 200

        messages = await client.get(f"/chats/{chat['id']}/messages", headers=auth(ALICE_ID))
        contents = [(m["role"], m["content"]) for m in messages.json()]
        assert ("assistant", "This document is about photosynthesis.") in contents

    assert dispatched["name"] == "notify_quiz_ready"
    assert dispatched["kwargs"]["quiz_id"] is None
    assert dispatched["kwargs"]["chat_id"] == chat["id"]


@pytest.mark.asyncio
async def test_callback_creates_quiz_row_for_quiz_intent(monkeypatch):
    monkeypatch.setattr("routes.celery_app.send_task", lambda *a, **k: None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Quiz-intent doc")
        chat = await create_chat(client, ALICE_ID, document["id"])
        user_message = await create_user_message(client, chat["id"], "Quiz me on chapter 1")

        response = await client.post(
            "/internal/chat-answers",
            json={
                "chat_id": chat["id"],
                "message_id": user_message["id"],
                "result": {
                    "intent": "quiz",
                    "question": "Quiz me on chapter 1",
                    "quiz_questions": ["Q1: What is a cell?"],
                },
            },
        )
        assert response.status_code == 200

        quizzes = await client.get("/quizzes", headers=auth(ALICE_ID))
        topics = [q["topic"] for q in quizzes.json()]
        assert "Quiz me on chapter 1" in topics


@pytest.mark.asyncio
async def test_callback_404s_for_nonexistent_chat():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/internal/chat-answers",
            json={
                "chat_id": "99999999-9999-9999-9999-999999999999",
                "message_id": "99999999-9999-9999-9999-999999999999",
                "result": {"intent": "answer", "answer": "x"},
            },
        )
        assert response.status_code == 404
```

- [ ] **Step 4: Run**

```bash
cd services/core-api
./.venv/bin/python -m pytest tests/test_chat_answers_callback.py -v
```
Expected: all 3 PASS.

- [ ] **Step 5: Full suite + lint**

```bash
./.venv/bin/python -m pytest tests/ -v
ruff check .
```
Note: `tests/test_chats_route.py`'s existing message tests (that mock
`routes.ask_question`) will now fail to collect/fail — `ask_question` no
longer exists. That's expected here; Task 4 rewrites those tests. Confirm
the *only* new failures are in `test_chats_route.py`'s message-related tests
and the two pre-existing celery-retry-worker failures; nothing else should
regress.

- [ ] **Step 6: Commit**

```bash
git add services/core-api/agentic_client.py services/core-api/routes.py \
  services/core-api/tests/test_chat_answers_callback.py
git commit -m "feat(core-api): add POST /internal/chat-answers callback"
```

---

### Task 4: Simplify `POST /chats/{chat_id}/messages` to async (202)

**Files:**
- Modify: `services/core-api/routes.py`
- Modify: `services/core-api/tests/test_chats_route.py`

**Interfaces:**
- Consumes: `agentic_client.request_answer` (Task 3).

- [ ] **Step 1: Replace `create_message`**

```python
@router.post("/chats/{chat_id}/messages", status_code=202)
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
        await request_answer(str(chat_id), str(user_message.id), str(chat.document_id), request.content)
    except Exception as e:
        log.warning("chat_message_agentic_dispatch_failed", chat_id=str(chat_id), error=str(e))
        raise HTTPException(status_code=502, detail="Failed to dispatch question to agentic")

    log.info("chat_message_dispatched", chat_id=str(chat_id), user_id=str(user.id))
    return {"user_message": user_message}
```

- [ ] **Step 2: Rewrite the message tests in `test_chats_route.py`**

Replace `test_create_message_happy_path`, `test_create_message_502s_on_agentic_failure_keeps_user_row`,
and `test_messages_ordered_by_created_at_asc` (the ones that mock
`routes.ask_question` and assert on a synchronous `assistant_message`):

```python
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
```

Delete `test_messages_ordered_by_created_at_asc` (it tested ordering across
a synchronous user+assistant pair in one request, which no longer happens —
message ordering itself is still covered by the callback test in Task 3 and
isn't `POST /chats/{chat_id}/messages`-specific behavior).

In `test_cross_user_chat_access_denied_matrix`, change the expected status
for the cross-user `POST .../messages` call from `404` (unchanged — still
404, ownership check runs before dispatch) — verify this test doesn't
reference `routes.ask_question` anywhere; if it does, update the monkeypatch
target to `routes.request_answer`.

- [ ] **Step 3: Run**

```bash
cd services/core-api
./.venv/bin/python -m pytest tests/test_chats_route.py -v
```
Expected: all PASS.

- [ ] **Step 4: Full suite + lint**

```bash
./.venv/bin/python -m pytest tests/ -v
ruff check .
```
Expected: only the 2 pre-existing celery-retry-worker failures remain.

- [ ] **Step 5: Commit**

```bash
git add services/core-api/routes.py services/core-api/tests/test_chats_route.py
git commit -m "feat(core-api): make POST /chats/{chat_id}/messages async (202)"
```

---

### Task 5: Remove direct quiz-creation endpoints and their test surface

**Files:**
- Modify: `services/core-api/routes.py`
- Modify: `services/core-api/agentic_client.py`
- Modify: `services/core-api/worker.py`
- Delete: `services/core-api/tests/test_worker_generate_quiz.py`
- Delete: `services/core-api/tests/test_worker_generate_quiz_retry.py`
- Modify: `services/core-api/tests/test_routes.py`
- Modify: `services/core-api/tests/test_document_upload_route.py`

- [ ] **Step 1: Remove `POST /quizzes` and `POST /quizzes/generate` from `routes.py`**

Delete `create_quiz`, `generate_quiz_request`, and the now-unused
`QuizCreateRequest`/`GenerateQuizRequest` Pydantic models. `list_quizzes`,
`get_quiz`, `update_quiz`, `delete_quiz`, `_get_owned_quiz`,
`create_quiz_attempt`, `get_quiz_stats` all stay — quizzes are still
readable/manageable, just no longer directly creatable by a client (only via
the chat-intent path from Task 3).

- [ ] **Step 2: Remove `request_quiz` from `agentic_client.py`**

It has no callers left after `generate_quiz` (Step 3 below) is deleted.

- [ ] **Step 3: Remove `generate_quiz` from `worker.py`**

Delete `generate_quiz`, `_insert_quiz`, `_mark_document_failed`,
`GENERATE_QUIZ_RETRY_COUNTDOWN`, and the `from agentic_client import
request_quiz` import. `notify_quiz_ready` and its imports/env vars stay.

- [ ] **Step 4: Delete the orphaned test files**

```bash
rm services/core-api/tests/test_worker_generate_quiz.py
rm services/core-api/tests/test_worker_generate_quiz_retry.py
```

- [ ] **Step 5: Rewrite the `create_quiz` test helper to insert directly**

`test_routes.py`'s `create_quiz` helper currently does `POST /quizzes` — that
endpoint is gone. Replace it with a direct DB insert (needed by every
existing CRUD/stats/quiz_attempts/cross-user test that uses it as a fixture):

```python
async def create_quiz(client: AsyncClient, user_id: str, document_id: str, topic: str) -> dict:
    engine = create_async_engine(DATABASE_URL)
    AsyncTestSession = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with AsyncTestSession() as session:
        quiz = Quiz(document_id=document_id, topic=topic, questions=[{"q": "2+2?", "a": "4"}])
        session.add(quiz)
        await session.commit()
        await session.refresh(quiz)
        result = {"id": str(quiz.id), "document_id": str(quiz.document_id), "topic": quiz.topic}
    await engine.dispose()
    return result
```

Add `from models import Quiz` to `test_routes.py`'s imports (alongside
whatever's already imported from `models`, if anything — check the current
import block first).

Delete `test_create_quiz_dispatches_notify_quiz_ready_task`,
`test_create_quiz_succeeds_even_when_task_dispatch_fails`, and
`test_create_quiz_on_other_users_document_returns_404` — all three test
`POST /quizzes` directly, which no longer exists. Every other test using
`create_quiz` as a fixture (CRUD, stats, quiz_attempts, cross-user matrix)
keeps working against the rewritten helper unchanged.

- [ ] **Step 6: Remove the generate-quiz tests from `test_document_upload_route.py`**

Delete `test_generate_quiz_409s_when_document_not_ready` and
`test_generate_quiz_404s_on_other_users_document` — both test
`POST /quizzes/generate`, which no longer exists.

- [ ] **Step 7: Run the full suite + lint**

```bash
cd services/core-api
./.venv/bin/python -m pytest tests/ -v
ruff check .
```
Expected: PASS except the 2 pre-existing celery-retry-worker failures (which
now includes only `test_worker_retry.py`, since `test_worker_generate_quiz_retry.py`
is deleted — update your expectation to "1 pre-existing failure", not 2, for
this task onward).

- [ ] **Step 8: Commit**

```bash
git add services/core-api/routes.py services/core-api/agentic_client.py services/core-api/worker.py \
  services/core-api/tests/test_routes.py services/core-api/tests/test_document_upload_route.py
git rm services/core-api/tests/test_worker_generate_quiz.py services/core-api/tests/test_worker_generate_quiz_retry.py
git commit -m "feat(core-api): remove direct quiz-creation endpoints (chat-intent only now)"
```

---

## Out of scope (explicitly not built this phase)

- Retry/idempotency on the agentic→core-api callback (Resolved Decision 5).
- Any polling/job-status endpoint for the client to know when an assistant
  reply has arrived (Resolved Decision 2) — same "no polling machinery"
  stance as the original `/quizzes/generate`.
- Fixing `services/agentic/mcp/server.py`'s already-broken `/query` calls or
  its now-broken `/agent` call (Resolved Decision 6) — pre-existing,
  out-of-scope breakage.
- Any change to `/evaluate` or the human-in-the-loop quiz-answering flow.
- Renaming `notify_quiz_ready`/`NotifyQuizReady`/`NotifyQuizReady` queue name
  to something generic (Resolved Decision 1).

## Post-implementation

- [ ] Run the full-repo test suites for all three services once, back to back,
  to confirm nothing outside the touched files regressed:
  `core-api` (`pytest tests/ -v`), `notifications` (`npm test`), and a manual
  smoke test of `agentic`'s `/agent` endpoint returning 202 immediately.
- [ ] Regenerate `docs/architecture.md`'s ER diagram section (`notifications`
  now has `chat_id`/`message_id` columns) and add a new hand-saved sequence
  diagram for this async chat flow, following the existing convention in that
  file (the `/arch` command that used to automate this no longer exists —
  see CLAUDE.md's Gotchas).
