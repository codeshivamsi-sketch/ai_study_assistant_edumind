# Lock compose form while awaiting reply + inline quiz CTAs in message

## Context

Chat is fully async (`POST /chats/{chat_id}/messages` returns 202
immediately; the real answer arrives later via RQ → callback →
Celery-dispatched notification → `edumind:notification` CustomEvent that
`ChatDetail` already subscribes to and uses to refetch messages). Today
`ChatDetail.tsx`'s `sending` state only covers the instant POST-ack, so
the Send button/input re-enable well before the actual reply shows up —
nothing stops (or signals) sending a second message while the first is
still in flight. Fix: track "waiting for the reply to arrive" separately
from "the POST call itself is in flight," and keep the compose form
locked with a "Please wait, processing…" message until the matching
notification arrives.

Separately, quiz CTAs ("Answer"/"Stats") currently render in an entirely
disconnected section below the message list, filtered only by
`document_id` — every quiz ever created for the document shows there,
with no link back to the specific assistant message that announced it.
Confirmed by reading the exact callback code
(`services/core-api/routes.py:309-377`, `receive_chat_answer`): `Quiz`
and the assistant `Message` are two independent inserts with no FK
between them today — `messages` has no `quiz_id` column. The only
existing quiz↔message pairing is transient, living in the notification
event dispatched right after both are created
(`quiz_id`/`message_id` passed together into the `notify_quiz_ready`
Celery task). That's not queryable after the fact and doesn't survive a
page reload, so it can't drive "render the CTA inside the right message
bubble." The correct minimal fix is a persisted `messages.quiz_id`
column, set once at the exact point in `receive_chat_answer` where the
message and (if any) quiz are created together.

## Backend changes

### 1. `messages.quiz_id` column

**`services/core-api/models.py`** — add to `Message` (mirrors the
existing `Quiz`/`QuizAttempt` FK style in this file):
```python
quiz_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("quizzes.id", ondelete="SET NULL"), index=True, nullable=True)
```
`SET NULL` (not `RESTRICT`/`CASCADE`) — there's no quiz-delete endpoint
today, so this is precautionary: if one's ever added, a message's text
content should survive losing its quiz reference rather than being
deleted or blocking the quiz delete.

**New migration**, `down_revision = '9def510cc11a'` (current head), explicit
FK constraint name so `downgrade` can reference it precisely (this repo's
existing migrations only ever declare FKs inline on `create_table`, never
`add_column` + `create_foreign_key`, so there's no naming convention to
match — `fk_messages_quiz_id_quizzes` follows SQLAlchemy's own default
`fk_<table>_<column>_<reftable>` naming so it reads the same as if it had
been in the original `create_table`):
```python
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

def upgrade() -> None:
    op.add_column('messages', sa.Column('quiz_id', postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index(op.f('ix_messages_quiz_id'), 'messages', ['quiz_id'], unique=False)
    op.create_foreign_key(
        'fk_messages_quiz_id_quizzes', 'messages', 'quizzes', ['quiz_id'], ['id'], ondelete='SET NULL'
    )

def downgrade() -> None:
    op.drop_constraint('fk_messages_quiz_id_quizzes', 'messages', type_='foreignkey')
    op.drop_index(op.f('ix_messages_quiz_id'), table_name='messages')
    op.drop_column('messages', 'quiz_id')
```

**Known limitation, not fixed here**: existing quizzes created before
this migration have no message to attach to (no reliable backfill
signal — the pairing only ever existed transiently in a notification
event, most of which are long gone). Their CTAs simply won't appear
anywhere after this change, same class of trade-off as the earlier
merge-documents change dropping orphaned-document recovery UI. Fine for
this dev app; flag if that's not acceptable.

### 2. `receive_chat_answer` — set `quiz_id` on the assistant message

**`services/core-api/routes.py:309-377`** — reorder so the `quiz` insert
happens (and is flushed for its id) *before* the message is constructed,
then pass `quiz_id` into `Message(...)`. Same for the `quiz_answer`
(grading) branch, using `result_quiz.id`:

```python
chat = await db.get(Chat, request.chat_id)
if not chat:
    raise HTTPException(status_code=404, detail="Chat not found")

quiz = None
if request.result.get("intent") == "quiz":
    quiz = Quiz(
        document_id=chat.document_id,
        topic=request.result.get("question", "Chat quiz"),
        questions=request.result.get("quiz_questions", []),
        thread_id=request.result.get("thread_id"),
    )
    db.add(quiz)
    await db.flush()  # assigns quiz.id before the message that references it

attempt = None
result_quiz = None
if request.result.get("intent") == "quiz_answer":
    quiz_id = request.result.get("quiz_id")
    score = request.result.get("score")
    result_quiz = await db.get(Quiz, quiz_id) if quiz_id else None
    if result_quiz is None or result_quiz.document_id != chat.document_id or score is None:
        log.warning("quiz_answer_callback_invalid_payload", chat_id=str(request.chat_id), quiz_id=quiz_id)
        raise HTTPException(status_code=400, detail="Invalid quiz_answer payload")
    attempt = QuizAttempt(
        quiz_id=result_quiz.id,
        user_id=chat.user_id,
        answers={"feedback": request.result.get("feedback")},
        score=score,
    )
    db.add(attempt)

answer = _extract_answer(request.result)
assistant_message = Message(
    chat_id=request.chat_id,
    role="assistant",
    content=answer,
    quiz_id=quiz.id if quiz else (result_quiz.id if result_quiz else None),
)
db.add(assistant_message)

await db.commit()
await db.refresh(assistant_message)
if quiz:
    await db.refresh(quiz)
if attempt:
    await db.refresh(attempt)
# ... notify_quiz_id / celery_app.send_task block unchanged below
```
This links both the quiz-creation message (points at the new quiz) and
the grading-feedback message (points at the quiz that was just graded,
so its bubble can also offer "Stats"/re-"Answer") — same rendering logic
either way, no branch needed on the frontend.

**Correction, 2026-07-28 (same day)**: reverted the grading-feedback half
of this — the user explicitly wanted the Answer/Stats CTA on the
quiz-creation message only, not on the grading-feedback message.
`assistant_message.quiz_id` is now `quiz.id if quiz else None` (dropped
the `result_quiz.id` fallback for the `quiz_answer` branch). One-time SQL
cleanup was also run to clear `quiz_id` on already-existing
grading-feedback messages (keeping it only on the earliest message per
`quiz_id`), since the code fix alone doesn't touch already-persisted
rows:
```sql
UPDATE messages m
SET quiz_id = NULL
WHERE quiz_id IS NOT NULL
  AND id != (
    SELECT m2.id FROM messages m2
    WHERE m2.quiz_id = m.quiz_id
    ORDER BY m2.created_at ASC
    LIMIT 1
  );
```

### 3. Message serialization — confirmed, no change needed

`GET /chats/{chat_id}/messages` (`routes.py:242`) has no `response_model`
— like every other list/detail endpoint in this codebase, it returns
`Message` ORM instances directly and FastAPI serializes all columns.
`quiz_id` will appear in the JSON automatically once the column exists;
no explicit schema to touch.

## Frontend changes (`frontend/remote-chat/src/`)

### `types.ts`
Add `quiz_id: string | null;` to the `Message` interface.

### `routes/ChatDetail.tsx`

- **Drop the `quizzes` state and `listQuizzes` fetches entirely** (both
  in the mount effect and the notification handler) — no longer needed
  now that each message carries its own `quiz_id`. Drop the `relatedQuizzes`
  computation and the whole separate "Quizzes from this document"
  section. Drop the now-unused `Quiz` type import and `listQuizzes`
  import from `../api` (delete `listQuizzes` from `api.ts` too if this
  was its only caller — check `QuizAnswer.tsx`/`QuizStats.tsx` don't use
  it; they call `getQuiz`/`getQuizStats` directly by id, not the list).

- **Inline the quiz CTA into the message bubble**: in the messages map,
  render Answer/Stats links inside the same `<Card>` when
  `m.quiz_id` is set:
  ```tsx
  {messages.map((m) => (
    <Card key={m.id} className={m.role === "assistant" ? styles.assistant : styles.user}>
      <p className={styles.role}>{m.role}</p>
      <p>{m.content}</p>
      {m.quiz_id && (
        <p className={styles.quizActions}>
          <Link to={`/chat/${chatId}/quiz/${m.quiz_id}/answer`}>Answer</Link>{" "}
          <Link to={`/chat/${chatId}/quiz/${m.quiz_id}/stats`}>Stats</Link>
        </p>
      )}
    </Card>
  ))}
  ```

- **Add `awaitingReply` state**, separate from `sending`:
  ```tsx
  const [awaitingReply, setAwaitingReply] = React.useState(false);
  ```
  Set `true` right after a successful `sendMessage` ack in `handleSend`
  (alongside the existing `setDraft("")`). Clear it in the notification
  handler's existing `detail.chatId === chatId` branch, alongside the
  existing `refreshMessages()` call — that's the exact same signal
  already used to know "something changed for this chat," so no new
  correlation logic is needed (single-question-in-flight UI, matches how
  the rest of this screen already works).

- **Lock the form while `sending || awaitingReply`**:
  ```tsx
  <form onSubmit={handleSend} className={styles.composeForm}>
    <TextInput
      label="Ask a question, or say 'quiz me' / 'summarize this'"
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      disabled={sending || awaitingReply}
    />
    <Button type="submit" disabled={sending || awaitingReply}>
      {sending ? "Sending…" : awaitingReply ? "Processing…" : "Send"}
    </Button>
  </form>
  {awaitingReply && <p className={styles.pending}>Please wait, processing…</p>}
  {sendError && <p className={styles.error}>Failed to send: {sendError}</p>}
  ```
  `TextInput` and `Button` already spread native props (confirmed in
  `design-system/src/Button.tsx`), so `disabled` needs no new plumbing.

  Known limitation, not solved here (not asked for): if the reply never
  arrives (worker crash, dropped notification), the form stays locked
  until the user navigates away and back — no timeout/retry. Matches the
  existing fire-and-forget architecture's lack of a dead-letter/timeout
  story; out of scope for this change.

### `routes/ChatDetail.module.css`
- Add `.quizActions` (small flex row, e.g. `display: flex; gap: 12px; margin-top: 8px;`).
- Add `.pending` (muted helper text, matching the existing `.fileLabel`-style
  `color: #5c6270; font-size: 13px;` convention used elsewhere in this repo).
- Drop the now-unused `.quizzes` class (the removed section's wrapper).

## Verification

- `alembic upgrade head` from `services/core-api`, confirm `messages`
  gains a nullable `quiz_id` column with an FK to `quizzes.id`.
- `pytest tests/ -v` — existing chat-answer-callback tests
  (`test_chat_answers_callback.py`) should still pass; add/extend one
  assertion that a quiz-intent callback's resulting message row has
  `quiz_id` set to the created quiz's id, and a quiz_answer callback's
  message has `quiz_id` set to the graded quiz's id.
- Typecheck `remote-chat` (`npx tsc --noEmit`).
- Browser: ask a question in an existing chat — Send button and text
  input should visibly disable and show "Please wait, processing…"
  immediately after submit, and only re-enable once the assistant's
  reply appears (matches current notification-poll cadence, ~10s).
- Browser: say "quiz me" in a chat about a ready document — the
  resulting assistant message bubble itself should carry "Answer"/
  "Stats" links, with no separate "Quizzes from this document" section
  anywhere on the page. Answer the quiz — the grading-feedback message
  bubble should also carry "Answer"/"Stats" links pointing at the same
  quiz.
