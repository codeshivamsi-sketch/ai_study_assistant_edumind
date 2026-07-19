# Async Quiz Notification (Phase B3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the `notifications` gRPC call out of `POST /quizzes`'s request path entirely, into a retrying Celery task, so a slow or unreachable `notifications` service can never add latency (or risk) to quiz creation.

**Architecture:** `core-api`'s existing (previously idle) Celery app gets one task, `notify_quiz_ready`, registered under that exact string name. `POST /quizzes` dispatches it via `celery_app.send_task(...)` instead of calling gRPC directly; the task itself (running in the `worker` process) makes the real gRPC call and retries up to 3 times with a configurable countdown on failure.

**Tech Stack:** Celery 5.6 (already a dependency, previously unused), Redis (existing broker), the existing `grpc_client.notify_quiz_ready` function from Phase B2.

## Global Constraints

- `POST /quizzes` keeps returning **200** (not 201, not 202) — the quiz itself is still created synchronously and returned complete; only the notification becomes async.
- The Celery task is registered with the exact name `"notify_quiz_ready"` — `celery_app.send_task("notify_quiz_ready", ...)` dispatches by that literal string, and Celery's default naming (module-qualified path) would not match unless `name=` is set explicitly on the task decorator.
- `self.retry(...)` must be used as `raise self.retry(...)` — calling it without `raise` lets execution fall through past the retry point.
- Dispatching the task (`send_task`, a synchronous broker publish) is itself best-effort: if it raises (e.g. Redis unreachable), quiz creation must still succeed and return 200 — same invariant Phase B2 established for the gRPC call, now extended to cover broker publish failures too.
- Retry countdown is configurable via `NOTIFY_QUIZ_READY_RETRY_COUNTDOWN` (env var, default `"60"`) specifically so it can be shrunk for the retry integration test without touching the retry logic.
- The `worker` service in `docker-compose.yml` needs `NOTIFICATIONS_GRPC_URL` — the gRPC call now happens in that process, not `core-api`'s.

---

### Task 1: `worker.py` — the `notify_quiz_ready` Celery task

**Files:**
- Modify: `services/core-api/worker.py`
- Create: `services/core-api/tests/test_worker.py`

**Interfaces:**
- Consumes: `grpc_client.notify_quiz_ready(user_id: str, quiz_id: str) -> None` (existing, from Phase B2 — raises `grpc.RpcError` on failure).
- Produces: `celery_app` (existing, unchanged export) and a Celery task registered under the name `"notify_quiz_ready"`, consumed by Task 2 (`routes.py`'s `send_task` call) and Task 4 (the retry integration test).

- [ ] **Step 1: Write the failing test**

Create `services/core-api/tests/test_worker.py`:

```python
from worker import notify_quiz_ready


def test_notify_quiz_ready_calls_grpc_client(monkeypatch):
    called = {}

    def fake_send(user_id, quiz_id):
        called["user_id"] = user_id
        called["quiz_id"] = quiz_id

    monkeypatch.setattr("worker.send_grpc_notification", fake_send)

    result = notify_quiz_ready.apply(args=["u1", "q1"])

    assert result.successful()
    assert called == {"user_id": "u1", "quiz_id": "q1"}
```

`.apply()` runs the task synchronously in the current process (no broker or
running worker needed) — the right tool for testing the task's own logic in
isolation, distinct from Task 4's integration test which needs a real
worker.

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/core-api
source /tmp/edumind_venv/bin/activate 2>/dev/null || (python3 -m venv /tmp/edumind_venv && source /tmp/edumind_venv/bin/activate && pip install -q -r requirements.txt)
python -m pytest tests/test_worker.py -v
```

Expected: FAIL — `ImportError: cannot import name 'notify_quiz_ready' from 'worker'` (the task doesn't exist yet).

- [ ] **Step 3: Write the task**

Modify `services/core-api/worker.py` — replace the entire file contents:

```python
from celery import Celery
from grpc_client import notify_quiz_ready as send_grpc_notification
import os

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
RETRY_COUNTDOWN = int(os.getenv("NOTIFY_QUIZ_READY_RETRY_COUNTDOWN", "60"))

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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd services/core-api
python -m pytest tests/test_worker.py -v
```

Expected: `test_notify_quiz_ready_calls_grpc_client PASSED`.

- [ ] **Step 5: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/core-api/worker.py services/core-api/tests/test_worker.py
git commit -m "feat(core-api): add notify_quiz_ready Celery task with retry"
```

---

### Task 2: Wire `POST /quizzes` to dispatch the task instead of calling gRPC directly

**Files:**
- Modify: `services/core-api/routes.py`
- Modify: `services/core-api/tests/test_routes.py`

**Interfaces:**
- Consumes: `celery_app` (Task 1, `from worker import celery_app`).
- Produces: `create_quiz` no longer imports or calls `grpc`/`notify_quiz_ready` — nothing downstream depends on those names in `routes.py` anymore.

- [ ] **Step 1: Write the failing tests**

Modify `services/core-api/tests/test_routes.py` — replace the import block at
the top (drop `import grpc`, it's no longer used in this file):

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from main import app
from database import get_db
import pytest
from httpx import AsyncClient, ASGITransport
```

Replace the two existing gRPC-mock tests (`test_create_quiz_calls_notify_quiz_ready`
and `test_create_quiz_succeeds_even_when_notify_quiz_ready_raises`) with:

```python
@pytest.mark.asyncio
async def test_create_quiz_dispatches_notify_quiz_ready_task(monkeypatch):
    dispatched = {}

    def fake_send_task(name, args=None, **kwargs):
        dispatched["name"] = name
        dispatched["args"] = args

    monkeypatch.setattr("routes.celery_app.send_task", fake_send_task)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Notify notes")
        quiz = await create_quiz(client, ALICE_ID, document["id"], "Notify quiz")

    assert dispatched["name"] == "notify_quiz_ready"
    assert dispatched["args"] == [ALICE_ID, quiz["id"]]


@pytest.mark.asyncio
async def test_create_quiz_succeeds_even_when_task_dispatch_fails(monkeypatch):
    def failing_send_task(name, args=None, **kwargs):
        raise ConnectionError("simulated broker failure")

    monkeypatch.setattr("routes.celery_app.send_task", failing_send_task)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Resilience notes")
        quiz = await create_quiz(client, ALICE_ID, document["id"], "Resilience quiz")

    assert quiz["topic"] == "Resilience quiz"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/core-api
python -m pytest tests/test_routes.py::test_create_quiz_dispatches_notify_quiz_ready_task tests/test_routes.py::test_create_quiz_succeeds_even_when_task_dispatch_fails -v
```

Expected: FAIL — `monkeypatch.setattr("routes.celery_app.send_task", ...)` raises `AttributeError`, since `routes.py` doesn't import `celery_app` yet.

- [ ] **Step 3: Modify routes.py**

Modify `services/core-api/routes.py` — replace the import block at the top
(drop `asyncio`, `grpc`, `from grpc_client import notify_quiz_ready`; add
`from worker import celery_app`):

```python
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import Any, Optional
import uuid

from database import get_db
from identity import get_current_user
from models import User, Document, Quiz, QuizAttempt
from logger import log
from worker import celery_app

router = APIRouter()
```

Then modify `create_quiz`:

```python
@router.post("/quizzes")
async def create_quiz(
    request: QuizCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_owned_document(request.document_id, user, db)
    quiz = Quiz(document_id=request.document_id, topic=request.topic, questions=request.questions)
    db.add(quiz)
    await db.commit()
    await db.refresh(quiz)
    try:
        celery_app.send_task("notify_quiz_ready", args=[str(user.id), str(quiz.id)])
    except Exception as e:
        log.warning("notify_quiz_ready_dispatch_failed", quiz_id=str(quiz.id), error=str(e))
    return quiz
```

- [ ] **Step 4: Run the new tests and the full suite to verify they pass**

```bash
cd services/core-api
python -m pytest tests/ -v
```

Expected: all 13 tests pass (same count as before — two tests were
replaced, not added).

- [ ] **Step 5: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/core-api/routes.py services/core-api/tests/test_routes.py
git commit -m "feat(core-api): dispatch notify_quiz_ready via Celery instead of calling gRPC directly"
```

---

### Task 3: Fix `docker-compose.yml` — `worker` needs `NOTIFICATIONS_GRPC_URL`

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:** none (config only).

- [ ] **Step 1: Add the missing env var**

Modify `docker-compose.yml` — in the `worker` service's `environment` block,
add `NOTIFICATIONS_GRPC_URL`:

```yaml
  worker:
    build:
      context: .
      dockerfile: services/core-api/Dockerfile
    depends_on:
      - redis
      - postgres
    environment:
      DATABASE_URL: postgresql+asyncpg://edumind:edumind@postgres:5432/edumind
      REDIS_URL: redis://redis:6379/0
      NOTIFICATIONS_GRPC_URL: notifications:5001
    command: celery -A worker worker --loglevel=info
```

(Only the `environment` block changes — `build`, `depends_on`, and `command`
stay exactly as they are today.)

- [ ] **Step 2: Verify the compose file is still valid YAML**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
docker compose config --quiet && echo "valid"
```

Expected: `valid`, no errors.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "fix(compose): give worker service NOTIFICATIONS_GRPC_URL

The gRPC call now happens inside the worker process (Task 1), not
core-api's — only core-api had this env var before."
```

---

### Task 4: Integration test — retry logic against a real worker

**Files:**
- Create: `services/core-api/tests/test_worker_retry.py`

**Interfaces:**
- Consumes: `celery_app` (Task 1), the `"notify_quiz_ready"` task name (Task 1), `NOTIFY_QUIZ_READY_RETRY_COUNTDOWN` env var (Task 1).

This test requires a **separate, dedicated Celery worker process** (not the
docker-compose `worker` service, which points at the real `notifications`
service) — one started specifically for this test, pointed at an
unreachable gRPC address and a short retry countdown, so every attempt
fails deterministically and the full retry cycle runs fast.

- [ ] **Step 1: Write the test**

Create `services/core-api/tests/test_worker_retry.py`:

```python
import time
from celery.result import AsyncResult
from worker import celery_app

ALICE_ID = "11111111-1111-1111-1111-111111111111"


def test_notify_quiz_ready_retries_then_fails():
    task = celery_app.send_task("notify_quiz_ready", args=[ALICE_ID, "22222222-2222-2222-2222-222222222222"])
    result = AsyncResult(task.id, app=celery_app)

    start = time.monotonic()
    timeout = 15
    while not result.ready() and time.monotonic() - start < timeout:
        time.sleep(0.2)
    elapsed = time.monotonic() - start

    assert result.ready(), f"task did not finish within {timeout}s (state={result.state})"
    assert result.state == "FAILURE"
    # 3 retries at ~1s each (NOTIFY_QUIZ_READY_RETRY_COUNTDOWN=1 in this
    # test's worker env) — proves the retry loop actually ran more than
    # once, not that it failed immediately on the first attempt.
    assert elapsed >= 2, f"expected at least ~3s of retries, only took {elapsed:.1f}s"
```

- [ ] **Step 2: Start a dedicated worker for this test and run it**

`--pool=solo` keeps the worker single-process — the default prefork pool
forks child processes that `kill $WORKER_PID` below would not reach,
leaving orphaned workers holding Redis connections after the test.

```bash
cd services/core-api
source /tmp/edumind_venv/bin/activate
export DATABASE_URL="postgresql+asyncpg://edumind:edumind@localhost:5432/edumind"
export REDIS_URL="redis://localhost:6379/0"
export NOTIFICATIONS_GRPC_URL="localhost:59999"
export NOTIFY_QUIZ_READY_RETRY_COUNTDOWN="1"
celery -A worker worker --loglevel=info --pool=solo &
WORKER_PID=$!
sleep 3
python -m pytest tests/test_worker_retry.py -v
TEST_EXIT=$?
kill $WORKER_PID
wait $WORKER_PID 2>/dev/null
exit $TEST_EXIT
```

Expected: `test_notify_quiz_ready_retries_then_fails PASSED`. The worker's
own log output (visible while it's running in the foreground/background)
should show three `Retry` log lines for the task before it finally logs
failure — confirms `max_retries=3` was honored, not skipped.

- [ ] **Step 3: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/core-api/tests/test_worker_retry.py
git commit -m "test(core-api): add retry integration test for notify_quiz_ready

Runs against a real worker process with a short retry countdown
(NOTIFY_QUIZ_READY_RETRY_COUNTDOWN=1) and an unreachable gRPC target,
so the full 3-retry cycle is exercised in seconds instead of minutes."
```

---

### Task 5: Full-stack manual verification

**Files:** none (verification only).

- [ ] **Step 1: Bring up the full stack**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
docker-compose up --build -d
```

If `core-api`'s port 8000 is already held by an unrelated container on this
machine (a known recurring environment issue from earlier phases), skip
straight to a local run: `uvicorn main:app --host 0.0.0.0 --port 8080` from
`/tmp/edumind_venv`, adjusting the curl commands below to port 8080. Bring
up at least `postgres`, `redis`, `notifications`, and `worker` via
`docker-compose up -d postgres redis notifications worker` regardless.

- [ ] **Step 2: Confirm the worker container has the new env var**

```bash
docker exec python_backend_refresher-worker-1 printenv NOTIFICATIONS_GRPC_URL
```

Expected: `notifications:5001`.

- [ ] **Step 3: Create a quiz and confirm the response is immediate and 200**

```bash
ALICE_ID="11111111-1111-1111-1111-111111111111"

DOC_ID=$(curl -s -X POST http://localhost:8000/documents \
  -H "X-User-Id: $ALICE_ID" -H "Content-Type: application/json" \
  -d '{"title": "B3 notes", "status": "uploaded"}' | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

time curl -s -X POST http://localhost:8000/quizzes \
  -H "X-User-Id: $ALICE_ID" -H "Content-Type: application/json" \
  -d "{\"document_id\": \"$DOC_ID\", \"topic\": \"B3 quiz\", \"questions\": []}"
```

Expected: HTTP 200 with the quiz body, and the `time` output shows the
request completing quickly (no multi-second gRPC-call latency in the
response path — that work now happens in `worker`, after the response is
already sent).

- [ ] **Step 4: Confirm the worker consumed the task**

```bash
docker logs python_backend_refresher-worker-1 --tail 20
```

Expected: a log line showing the `notify_quiz_ready` task received and
succeeded (no retry/failure lines, since the real `notifications` service
is reachable in this run).

- [ ] **Step 5: Confirm the notification landed**

```bash
QUIZ_ID=$(curl -s http://localhost:8000/quizzes -H "X-User-Id: $ALICE_ID" | python3 -c "import sys, json; print(json.load(sys.stdin)[-1]['id'])")
curl -s "http://localhost:5000/notifications?user_id=$ALICE_ID" -H "X-User-Id: $ALICE_ID"
```

Expected: the response includes a row with `"quiz_id": "<QUIZ_ID>"` and
`"message": "Your quiz is ready!"`.

- [ ] **Step 6: Run both test suites once more against this stack**

```bash
cd services/core-api && python -m pytest tests/ -v
```

Expected: all 14 tests pass (13 from Task 2 + `test_worker.py`'s 1 test —
`test_worker_retry.py` is excluded here since it needs its own dedicated
worker env, already verified in Task 4).

No commit for this task — verification only.
