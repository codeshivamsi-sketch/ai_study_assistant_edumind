# Async quiz-answer evaluation flow — design

## Context

Goal: let a client reply to a quiz question inside an existing chat thread
and get the answer evaluated asynchronously, following the exact same
enqueue → RQ worker → callback → notify skeleton `POST
/chats/{chat_id}/messages` already uses for regular chat answers (see
[async-chat-rq-pipeline](2026-07-26-async-chat-rq-pipeline.md)) — not a new
architecture.

The originally proposed shape assumed core-api could just branch on a new
`intent` field and call agentic's `/evaluate` endpoint the same way it calls
`/agent` today. Inspecting the actual code surfaced several load-bearing gaps:

- `/evaluate` already exists in `services/agentic/api/main.py`, but it's
  **synchronous** (no RQ enqueue, unlike `/agent`), and its request shape is
  `{thread_id, user_answer}` — not `{chat_id, document_id, question}` like
  `/agent`. It resumes a LangGraph checkpoint that was paused after the
  `quiz` node (`interrupt_after=["quiz"]` in `agents/agents.py`).
- That `thread_id` is generated fresh per quiz request in `run_agent_job`
  (`thread_id = str(uuid.uuid4())`) and is **never durably stored** —
  today it only survives by accident, serialized into the assistant
  message's JSON blob (`_extract_answer`'s fallback branch, since a
  quiz-intent result has no `answer` key). There is currently no queryable
  place to look it up again to resume evaluation.
- `evaluator_node` (`agents/agents.py`) returns free-text prose only —
  `{"evaluation": "<LLM explanation>"}` — but `quiz_attempts.score` is a
  `Numeric` `NOT NULL` column. There is no numeric score anywhere in the
  current evaluation output.
- There is no explicit "pending/ready" status field for chat messages
  today, contrary to the original ask to "reuse or mirror" one — the
  existing signal is purely implicit (assistant message absent from `GET
  /chats/{chat_id}/messages` until the callback lands, plus a generic gRPC
  notify). No test files exist yet for `/agent` or `/evaluate` in agentic.

Decisions resolved with the user (see full brainstorming transcript):

1. `evaluator_node`'s prompt changes to require structured JSON output
   (`{"score": <0-10>, "feedback": "..."}`), parsed in the job — rather than
   storing a meaningless `score=0` or adding a second LLM call to extract one.
2. The client passes `quiz_id` explicitly when replying to a quiz (rather
   than core-api inferring "the most recent quiz in this chat"), since
   quizzes hang off `documents`, not `chats`, and a chat can have more than
   one quiz in flight.

## Client contract

`POST /chats/{chat_id}/messages` request body gains two optional fields:

```python
class MessageCreateRequest(BaseModel):
    content: str
    intent: Optional[str] = None         # "quiz_answer" or omitted
    quiz_id: Optional[uuid.UUID] = None  # required when intent == "quiz_answer"
```

- `intent` omitted → today's behavior is completely unchanged (agentic
  classifies answer/quiz/summarize itself).
- `intent == "quiz_answer"` → `quiz_id` is required (400 if missing).
  core-api resolves it via the existing `_get_owned_quiz` helper (joins
  through `documents.user_id`) — 404, not 403, if it's missing or not the
  caller's, same as every other quiz lookup.
- Still returns `202 {user_message}` immediately, no inline wait — same
  enqueue-and-ack contract as the existing async path.

## Data model change

`quizzes` gets one new nullable column: `thread_id: Mapped[Optional[str]]`.
This is the missing link between a generated quiz and the LangGraph
checkpoint that can evaluate an answer to it. One Alembic migration adds the
column; the existing quiz-intent branch in `receive_chat_answer` sets it
from `result["thread_id"]` when it creates the `Quiz` row (that value is
already being sent today — it's just discarded).

## Agentic changes (`services/agentic`)

**`core/model.py`** — `EvaluateRequest` gains `chat_id`, `message_id`,
`quiz_id` (all required), mirroring `AgentRequest`'s `chat_id`/`message_id`.

**`api/main.py`** — `/evaluate` becomes enqueue-and-ack, mirroring what
`/agent` already does:

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

**`core/jobs.py`** — new `run_evaluate_job(thread_id, user_answer, chat_id,
message_id, quiz_id)`, moving the resume-from-interrupt logic currently
inline in `evaluate_endpoint` (`agent.update_state(..., as_node="quiz")`
then `agent.stream(None, config)`) out of the request path, then POSTing to
core-api's callback — same shape as `run_agent_job`.

**`agents/agents.py`** — `evaluator_node`'s system prompt changes from
free-text ("Give a score out of 10 and explain...") to requiring JSON
output (`{"score": <number 0-10>, "feedback": "<explanation>"}`), parsed
with `json.loads` in the node. This is the one behavior change to an
existing LLM call in this design.

## Core-api: callback handling

Reuses `POST /internal/chat-answers` rather than adding a new endpoint —
the existing endpoint already branches on `result["intent"]` to decide side
effects (it creates a `Quiz` row for `intent == "quiz"`), so a
`"quiz_answer"` branch fits the same generic-`result`-blob-plus-intent-switch
shape without a new schema, route, or auth mechanism:

- `result = {"intent": "quiz_answer", "quiz_id": ..., "score": <number>,
  "feedback": "..."}`
- Inserts an assistant `Message` with the feedback text — keeps the chat
  thread readable, consistent with every other intent.
- Inserts a `QuizAttempt` row: `quiz_id` from the payload, `user_id` looked
  up from `chat.user_id` (not trusted from the payload), `answers =
  {"feedback": ...}`, `score`. The `ON DELETE RESTRICT` invariant on
  `quiz_attempts.quiz_id`/`user_id` is untouched by this design.
- Same shared-secret `X-Internal-Token` auth already enforced on the route.

## Notification

Same `notify_quiz_ready` Celery task → gRPC call already used for the
`"quiz"` intent — no proto change needed (`quiz_id`/`chat_id`/`message_id`
are already optional, per the prior async-chat-rq-pipeline work). Called
with `quiz_id` (now meaningfully non-null for an evaluation), `chat_id`,
and `message_id`.

## Status tracking

No new status field is introduced. The implicit signal that already exists
for chat messages — the assistant reply's absence from `GET
/chats/{chat_id}/messages` until the callback lands, plus the gRPC notify —
is mirrored as-is for quiz-answer evaluation. There was no existing explicit
mechanism to reuse, so this design does not invent one.

## Testing

Following the repo's real-Postgres pytest convention (no mocks):

- Extend `test_chat_answers_callback.py` with a `quiz_answer`-intent case
  asserting a `QuizAttempt` row is created with the right `score`/`user_id`
  and an assistant message with the feedback text is inserted.
- Add `create_message` tests: 400 when `intent=quiz_answer` and `quiz_id`
  is missing; 404 when `quiz_id` isn't owned by the caller.
- Agentic gets its first tests for the evaluate path — `test_jobs.py`
  gains a `run_evaluate_job` test mirroring its existing `run_agent_job`
  test pattern (monkeypatch `agent.stream`/`httpx.post`, assert the POSTed
  payload shape).

## Out of scope

- Any polling/job-status endpoint — matches the existing "no polling
  machinery" stance for the chat-answer flow.
- Retry/idempotency on the agentic → core-api callback for this flow —
  matches the existing chat-answer callback's stance.
- Changing how quizzes are generated, or the `interrupt_after=["quiz"]`
  LangGraph structure itself — only the resume/evaluate side changes.
