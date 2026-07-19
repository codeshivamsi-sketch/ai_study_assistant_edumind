# Phase B3 — Background Jobs + Queuing: async quiz notification — design

## Context

Phase B2 wired `POST /quizzes` to call the `notifications` service's gRPC
`NotifyQuizReady` method synchronously from the request handler (made
non-blocking via `asyncio.to_thread` in a later fix, but still awaited
before the response). Phase B3 moves that call fully off the request path:
`core-api`'s Celery worker (configured since the original scaffold, never
used) picks up a `notify_quiz_ready` task and makes the gRPC call itself,
with retry-on-failure, so a slow or flaky `notifications` service can no
longer add any latency to `POST /quizzes` at all.

## Corrections to the original ask

- **Response code stays 200, not 202.** `POST /quizzes` currently returns
  200 (no explicit `status_code` was ever set — the original request's "202
  instead of 201" premise was wrong on both counts). The quiz itself is
  still created synchronously and returned complete in the body; only the
  *notification* becomes async. 202 is for when the primary resource isn't
  finished yet, which isn't the case here. Confirmed with the user during
  brainstorming.
- **Retry testing uses a real short-countdown integration test, not eager
  mode or a full 60s wait.** Confirmed with the user: make the countdown
  configurable via `NOTIFY_QUIZ_READY_RETRY_COUNTDOWN` (default 60), and in
  the automated test set it to ~1s so the retry cycle is real (real worker,
  real Redis, real delay) but fast.

## `worker.py` — the Celery task

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

Two things the literal request's pseudocode would have gotten wrong if
copied verbatim:

- **Explicit `name="notify_quiz_ready"`.** Celery's default task name is
  the module-qualified path (`worker.notify_quiz_ready`), not the bare
  function name. `celery_app.send_task('notify_quiz_ready', ...)` in
  `routes.py` dispatches by exact string name — without the explicit
  `name=`, that call would fail with `NotRegistered`.
- **Import alias.** `grpc_client.notify_quiz_ready` (the plain function that
  makes the gRPC call) and the new Celery task share the same conceptual
  name. Importing it as `send_grpc_notification` avoids the task function
  shadowing its own dependency.
- **`raise self.retry(...)`, not a bare `self.retry(...)` call.**
  `self.retry()` works by raising internally; without `raise`, execution
  would fall through past the retry and the task would appear to complete
  normally even though nothing succeeded.

`RETRY_COUNTDOWN` is read from `NOTIFY_QUIZ_READY_RETRY_COUNTDOWN` so the
integration test can shrink it to ~1s without touching the retry logic
itself.

## `routes.py` — `create_quiz`

Removes `asyncio.to_thread`, the `grpc` import, and `notify_quiz_ready`
entirely. After the existing `db.commit()`/`db.refresh(quiz)`, dispatches
the task instead of calling gRPC directly:

```python
from worker import celery_app
...

@router.post("/quizzes")
async def create_quiz(...):
    ...
    await db.commit()
    await db.refresh(quiz)
    try:
        celery_app.send_task("notify_quiz_ready", args=[str(user.id), str(quiz.id)])
    except Exception as e:
        log.warning("notify_quiz_ready_dispatch_failed", quiz_id=str(quiz.id), error=str(e))
    return quiz
```

Best-effort now covers the broker too, not just the gRPC call: if Redis is
down, `send_task` (a synchronous publish to the broker) can raise, and that
must not fail quiz creation either — the same invariant as Phase B2, now
generalized. Status code is unchanged (**200**, implicit).

## `docker-compose.yml`

The `worker` service is missing `NOTIFICATIONS_GRPC_URL` — only `core-api`
has it today, but `send_grpc_notification` now runs inside the `worker`
process, not `core-api`. Add
`NOTIFICATIONS_GRPC_URL: notifications:5001` to `worker`'s environment
block. No other infrastructure changes needed — `worker` already builds
from the same image as `core-api` (same `Dockerfile`, same generated
`notifications_pb2*.py` stubs, same `grpcio` dependency).

## Tests (`services/core-api/tests/test_routes.py`)

- **Replace** the two existing Phase-B2 tests that monkeypatch
  `routes.notify_quiz_ready` (that name no longer exists in `routes.py`)
  with two new tests monkeypatching `celery_app.send_task`:
  - `test_create_quiz_dispatches_notify_quiz_ready_task` — asserts
    `send_task` was called with `("notify_quiz_ready", args=[user.id,
    quiz.id])`.
  - `test_create_quiz_succeeds_even_when_task_dispatch_fails` — forces
    `send_task` to raise, asserts quiz creation still returns 200.
- **New integration test** for the retry path, requiring the real `worker`
  container/process and Redis running (same "hits real infra" convention
  as the rest of this test suite):
  - Set `NOTIFY_QUIZ_READY_RETRY_COUNTDOWN=1` and a `NOTIFICATIONS_GRPC_URL`
    pointing at an address nothing listens on, for the worker process
    running this test.
  - Dispatch `notify_quiz_ready` directly via `celery_app.send_task(...)`
    (not through the HTTP API — this test targets the task in isolation).
  - Poll `AsyncResult(task_id).state` until it reaches `FAILURE` or a
    timeout well beyond `3 × RETRY_COUNTDOWN` elapses.
  - Assert the task actually reached `FAILURE` (not `PENDING` forever, not
    a silent unhandled hang), and that elapsed wall-clock time is
    consistent with 3 retries at ~1s each (bounded check, not exact) —
    proving the retry loop actually ran 3 times rather than failing
    immediately on the first attempt.

## Manual verification (item 3 from the original request)

With the full stack up: `POST /quizzes` returns 200 immediately (no
gRPC-call latency in the response); the `worker` container's logs show the
`notify_quiz_ready` task consumed; a row appears in the `notifications`
service's `notifications` table shortly after, via the real gRPC → BullMQ
path already built in Phase B2. This is a real end-to-end check, not
automated.

## What's explicitly out of scope

- No change to the `notifications` service itself (Phase B2's gRPC server,
  BullMQ job, HTTP endpoints are all unaffected).
- No dead-letter queue, no alerting on final task failure beyond the
  existing `log.warning` pattern — `max_retries=3` then giving up silently
  (from the request's perspective; Celery's own result backend records the
  `FAILURE` state) matches the scope of this phase. A future phase could
  add that if needed.
