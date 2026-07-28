# Enforce document↔chat 1:1, atomic upload, auto-start chat

Status: implemented and verified end-to-end (2026-07-28).

## Context

Today a `Document` can be created with just a title (no file at all — the
`Document` model has no file-presence concept), and any number of `Chat`
rows can point at the same document (no uniqueness anywhere). Both are
loopholes left over from building the document and chat features
independently. Neither state makes sense in the actual product: a
title-only document has nothing to chat about, and a document only ever
needs one running conversation.

Three changes, confirmed with you:
1. A document can only be created together with a file — one atomic
   operation, not "create, then maybe upload."
2. Exactly one chat per document, enforced at the DB level, not just by
   UI convention.
3. A successful upload auto-creates (or reuses) that document's one chat
   and takes the user straight into it.

You asked whether remote-documents and remote-chat should be merged to
make the auto-navigate-into-chat step easier. They shouldn't be:
`react-router-dom` is already a shared singleton across all 5 federated
apps, and every remote renders under shell's one `<BrowserRouter>` — so
`remote-documents` calling `useNavigate()` to a path `remote-chat` owns
(`/chat/:chatId`) already works today with zero extra wiring, the same way
it would if they were one app. Merging would just undo real MFE-learning
value for a problem that's already solved by the existing architecture.
This becomes a documented cross-remote contract (like the notification
event bus already is), not a merge.

(Note, 2026-07-28: this "don't merge" call was revisited the same day —
see `2026-07-28-merge-documents-into-chat.md` — once the ask changed from
"make navigation easier" to "why do we need two microfrontends/pages at
all," which is a UX question this plan's reasoning didn't address.)

## Backend changes

### 1. Atomic `POST /documents` (`services/core-api/routes.py`)

Add `Form` to the fastapi import. Delete `DocumentCreateRequest` (dead —
no JSON body possible once this is multipart) and the entire
`POST /documents/{document_id}/upload` route. Replace `create_document`:

```python
@router.post("/documents")
async def create_document(
    title: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = Document(user_id=user.id, title=title, status="uploaded")
    db.add(document)
    await db.commit()
    await db.refresh(document)

    content = await file.read()
    document.status = "processing"
    await db.commit()
    try:
        await upload_document(str(document.id), file.filename, content)
    except Exception as e:
        document.status = "failed"
        await db.commit()
        log.warning("document_upload_failed", document_id=str(document.id), error=str(e))
        raise HTTPException(status_code=502, detail="Document ingestion failed")
    document.status = "ready"
    await db.commit()
    await db.refresh(document)
    log.info("document_uploaded", document_id=str(document.id))
    return document
```

Same status transitions and error handling as today's two-call flow, just
inlined into one endpoint. Everything else in the Documents section
(`_get_owned_document`, GET list/detail, PATCH, DELETE) is untouched.

### 2. Unique index on `chats.document_id`

New migration, `down_revision = 'b7e14f9a2c63'` (current head). This
codebase does uniqueness via `create_index(..., unique=True)` (see
`ix_users_email`), not `create_unique_constraint` — match that:

```python
"""add unique index on chats.document_id

Revision ID: 9def510cc11a
Revises: b7e14f9a2c63
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9def510cc11a'
down_revision: Union[str, Sequence[str], None] = 'b7e14f9a2c63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index('ix_chats_document_id', table_name='chats')
    op.create_index(op.f('ix_chats_document_id'), 'chats', ['document_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_chats_document_id', table_name='chats')
    op.create_index(op.f('ix_chats_document_id'), 'chats', ['document_id'], unique=False)
```

**Manual step before this migration runs**: the dev DB almost certainly has
documents with 2+ chats from earlier manual testing this session — the
unique index will fail to create until those are gone. Run once, by hand,
not encoded in the migration:

```sql
DELETE FROM chats c
USING chats c2
WHERE c.document_id = c2.document_id
  AND c.created_at < c2.created_at;
```

Keeps the newest chat per document, deletes older duplicates. This
cascades to `messages` (`ondelete='CASCADE'`) — the deleted chats' message
history goes with them. Flag this explicitly when running it.

### 3. Idempotent `POST /chats`

Look up an existing chat by `document_id` first; return it as-is if found
(before the readiness check), so the auto-start-chat frontend flow is safe
to call unconditionally without its own "does one already exist" check —
and so the invariant is enforced at the one real choke point, not
duplicated per caller:

```python
@router.post("/chats")
async def create_chat(
    request: ChatCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    document = await _get_owned_document(request.document_id, user, db)

    existing = await db.execute(select(Chat).where(Chat.document_id == document.id))
    chat = existing.scalar_one_or_none()
    if chat:
        return chat

    if document.status != "ready":
        raise HTTPException(status_code=409, detail="Document not ready for chat")
    chat = Chat(user_id=user.id, document_id=request.document_id, title=request.title)
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    log.info("chat_created", chat_id=str(chat.id), document_id=str(document.id), user_id=str(user.id))
    return chat
```

`_get_owned_document` already filters by `user.id`, so any chat found for
that `document_id` is necessarily this user's — no extra `user_id` filter
needed on the lookup.

## Frontend changes

### `frontend/remote-documents/src/`

- **`types.ts`**: add
  ```ts
  export interface ChatRecord {
    id: string;
    document_id: string;
    title: string | null;
  }
  ```
- **`api.ts`**: delete `createDocument` and `uploadDocumentFile`. Add:
  ```ts
  export async function uploadDocument(userId: string, title: string, file: File): Promise<DocumentRecord> {
    const formData = new FormData();
    formData.append("title", title);
    formData.append("file", file);
    const res = await fetch(`${CORE_API_URL}/documents`, {
      method: "POST",
      headers: { "X-User-Id": userId },
      body: formData,
    });
    if (!res.ok) throw new Error(`upload failed: ${res.status}`);
    return res.json();
  }

  export function createOrGetChat(userId: string, documentId: string, title?: string): Promise<ChatRecord> {
    return request("/chats", userId, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ document_id: documentId, title: title || undefined }),
    });
  }

  export function listChats(userId: string): Promise<ChatRecord[]> {
    return request("/chats", userId);
  }
  ```
  (`createOrGetChat`/`listChats` duplicate the shape already in
  `remote-chat/src/api.ts` — matches this repo's established convention of
  small per-remote API duplication over cross-remote imports, documented
  in `frontend/CONTRACTS.md`.)

- **`routes/DocumentUpload.tsx`**: `handleSubmit` becomes
  ```tsx
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !file) return;
    setStatus("uploading");
    setError(null);
    try {
      const document = await uploadDocument(session.userId, title.trim(), file);
      const chat = await createOrGetChat(session.userId, document.id, document.title);
      navigate(`/chat/${chat.id}`);
    } catch (err) {
      setStatus("error");
      setError(String(err));
    }
  }
  ```
  On failure (upload or chat-create), stays on the form with the inline
  error — no navigation. The document row (status `failed` if ingestion
  failed) still exists and is visible in `DocumentList`, same as today.

- **`routes/DocumentList.tsx`**: remove the inline title-only create form
  and its state/imports entirely. Keep the grid of existing documents and
  a single `<Link to="/upload">Upload new</Link>` as the only way to
  create a document.

- **`routes/DocumentDetail.tsx`**: replace the
  `<Link to="/chat?documentId=...">` with: fetch `listChats`, find the one
  whose `document_id` matches (same client-side-filter pattern already
  used in `ChatDetail` for quizzes). If found, link straight to
  `/chat/{chat.id}`. If not found (pre-existing document from before this
  change, or the rare case where upload succeeded but chat-create
  failed), show a "Start chat" button calling `createOrGetChat` then
  navigating — the page never dead-ends.

### `frontend/remote-chat/src/`

- **`routes/ChatList.tsx`**: remove the manual create-chat form
  (`document_id`/`title` inputs, `useSearchParams` prefill, `createChat`
  call) entirely — chats are now only ever created via the upload flow.
  Becomes a pure list of the user's existing chats.
- **`api.ts`**: delete `createChat` (no longer called from anywhere) and
  its now-unused import in `ChatList.tsx`.
- **`ChatList.module.css`**: drop the now-unused create-form classes.

### `frontend/CONTRACTS.md`

Add a new section (after the `edumind:notification` event section, before
"Shared singleton versions"):

```markdown
## `/chat/:chatId` cross-remote navigation

`remote-documents` navigates straight into a chat after a successful
upload (and from `DocumentDetail`'s "Start chat" fallback) by calling
`useNavigate()` with a path `remote-chat` owns (`/chat/:chatId`), not a
path exposed by `remote-documents` itself. This works with zero extra
wiring because `react-router-dom` is a genuine shared singleton across
all 5 federated apps, and every remote renders only `<Routes>/<Route>`
under the shell's single `<BrowserRouter>` — one history stack, one
router instance, shared by every remote's route tree.

Any remote may `navigate()` (or `<Link>`) to `/chat/:chatId` once it holds
a real chat id — no query-param handoff, no event needed. `remote-chat`
is the only remote that renders this route (`ChatApp.tsx` → `:chatId` →
`ChatDetail`).
```

(Superseded 2026-07-28 — see the merge plan; this section was rewritten
once `remote-documents` was retired and the upload flow moved
intra-`remote-chat`.)

## Docs to update

- **`CLAUDE.md`**: add "one chat per document (`chats.document_id` unique
  index), enforced at the DB level and idempotently at `POST /chats`" to
  the Invariants section; add a short Decision note that document
  creation and upload were merged into one atomic multipart
  `POST /documents` call.
- **`README.md`**: API endpoint table — delete the
  `POST /documents/{id}/upload` row, update `POST /documents`'s
  description to "multipart, atomic create+upload", note `POST /chats` is
  idempotent per `document_id`.
- **`docs/architecture.md`**: redraw the first ~15 lines of the upload
  sequence diagram (client → one `POST /documents` call/response instead
  of two calls); rest of the diagram (agentic ingestion, status
  transitions) is unchanged. Add a dated note about the atomic
  create+upload and 1:1 document↔chat change.

## Tests to update

- **`services/core-api/tests/test_document_upload_route.py`**: every test
  currently does `POST /documents` (JSON) then
  `POST /documents/{id}/upload` (multipart) as two calls — collapse into
  one multipart `POST /documents` call each. The
  "404 on other user's document" upload test has no second call to make
  anymore under the new atomic endpoint; drop it (ownership on documents
  is already covered by `_get_owned_document` via `get_document`,
  `update_document`, `delete_document` tests).
- **`services/core-api/tests/test_chats_route.py`**: its `create_document`
  helper posts JSON to `/documents`, which no longer accepts JSON — needs
  a multipart-upload helper instead (mirror the pattern in the upload
  tests: `monkeypatch.setattr("routes.upload_document", ...)` for a fake
  successful ingestion). Add a new idempotency test: two `POST /chats`
  calls with the same `document_id` return the same `chat["id"]`.
  `test_create_chat_409s_when_document_not_ready` stays structurally the
  same.
- Sweep: `grep -rn "documents/{.*}/upload\|DocumentCreateRequest\|upload_document_file" services/core-api/tests/` to catch anything missed.

## Build order

1. Backend: `routes.py` change, new migration, run the manual dedup SQL
   first, then `alembic upgrade head`, update the two test files, run
   `pytest tests/ -v`, then rebuild+restart `core-api`
   (`docker compose build core-api && docker compose up -d core-api`).
2. Frontend `remote-documents`: `types.ts`, `api.ts`, `DocumentList.tsx`,
   `DocumentUpload.tsx`, `DocumentDetail.tsx` — typecheck
   (`npx tsc --noEmit`), rebuild+restart the container.
3. Frontend `remote-chat`: `ChatList.tsx`, `api.ts`, `ChatList.module.css`
   — typecheck, rebuild+restart the container.
4. Docs: `CONTRACTS.md`, `README.md`, `docs/architecture.md`, `CLAUDE.md`.

## Verification (all passed, 2026-07-28)

- `curl -X POST http://localhost:8000/documents -H "X-User-Id: <alice>"`
  with no multipart body → 422 (title/file required) — confirmed.
- Upload a real PDF via `DocumentUpload` in the browser → landed
  automatically on `/chat/<uuid>` with no manual "start chat" step —
  confirmed.
- Two `POST /chats` calls with the same `document_id` → same `id` both
  times, one row in `chats` for that `document_id` — confirmed.
- `DocumentList` showed no create-without-file form — confirmed.
- `ChatList` showed no manual create form — confirmed.
- `DocumentDetail` for a document with an existing chat showed "Open
  chat"; for one without, showed "Start chat" and created-then-navigated
  on click — confirmed.
