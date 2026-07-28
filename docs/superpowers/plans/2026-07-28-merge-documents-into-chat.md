# Merge remote-documents into remote-chat (chat-first UX)

## Context

Today the frontend has "Documents" and "Chat" as two separate top-level
destinations (separate nav links, separate federated micro-frontends,
separate Docker services). Starting a chat requires: go to Documents →
Upload new → fill the form → land in the chat. The user wants one
destination — a chat list with a "New chat" button that leads straight
into "upload a document, then land in the new chat" — and is
questioning why this needs two separate microfrontends at all.

It doesn't. `DocumentUpload.tsx`'s existing submit logic already does
exactly what's wanted (`uploadDocument` → `createOrGetChat` → `navigate`
into the chat) — it's just stranded behind a page nobody needs to visit
in its own right. No document management feature (delete, browsing
failed/orphan uploads) exists in the UI today, so nothing is lost by
retiring the standalone Documents pages. The backend needs zero changes:
`POST /documents` (atomic multipart) and idempotent-per-`document_id`
`POST /chats` were already built exactly for this flow.

This fully retires `remote-documents` as a federated app (name, route,
Docker service, manifest entry) — not just unrouted dead code — since
that's the literal answer to "why do we need two microfrontends."

## Approach

Move the upload flow into `remote-chat` as a new route `/chat/new`
(reuses the proven full-page-form pattern already in this codebase —
no new modal/overlay primitive needed, and it's deep-linkable for free).
`ChatList` (remote-chat's `/chat` index) becomes the sole landing page
with a persistent "New chat" link.

### New files (`remote-chat`)

- **`src/routes/ChatNew.tsx`** — ported from
  `remote-documents/src/routes/DocumentUpload.tsx` almost verbatim: same
  title/file form, same `handleSubmit` (`uploadDocument` →
  `createOrGetChat` → `navigate('/chat/' + chat.id)`), just now an
  intra-remote navigation instead of cross-remote. Copy/heading reworded
  ("New chat" / "Upload a document to start a chat about it" / "Upload &
  start chat").
- **`src/routes/ChatNew.module.css`** — copy of
  `DocumentUpload.module.css` (`.form`, `.fileLabel`, `.error`), unchanged.

### Modified (`remote-chat`)

- **`src/types.ts`** — add `DocumentStatus` + `DocumentRecord`, copied
  verbatim from `remote-documents/src/types.ts`. `Chat`/`Message`/`Quiz`
  types untouched.
- **`src/api.ts`** — add `uploadDocument` (multipart POST `/documents`)
  and `createOrGetChat` (POST `/chats`, idempotent per `document_id`),
  ported from `remote-documents/src/api.ts`. `createOrGetChat` returns
  `Promise<Chat>` (remote-chat's existing type — no need for a separate
  `ChatRecord`, `Chat` already has `id`/`document_id`/`title`).
- **`src/ChatApp.tsx`** — add `<Route path="new" element={<ChatNew session={session} />} />`
  (static segment, so no ranking conflict with `:chatId` regardless of
  order — place before `:chatId` for readability). Update the stale
  top-of-file comment that currently points to
  `remote-documents/src/DocumentsApp.tsx` for the "no own BrowserRouter"
  rationale — that file won't exist anymore.
- **`src/routes/ChatList.tsx`** — add a persistent `Link to="/chat/new"`
  ("+ New chat") next to the "Chats" heading (not just on the empty
  state), reword the empty-state copy off "Upload a document to start
  one" since there's no separate Documents destination anymore.
- **`src/routes/ChatList.module.css`** — small `.header` flex rule for
  the heading+link row.

### Deleted

- **`frontend/remote-documents/`** — entire directory (webpack config,
  Dockerfile, nginx.conf, src/, public/, dist/). Nothing left unrouted.
- **`frontend/shell/src/routes/DocumentsRoute.tsx`** — deleted.

### Shell

- **`src/App.tsx`** — drop the `DocumentsRoute` import and its
  `<Route path="/documents/*" .../>`; change the `/` redirect from
  `/documents` to `/chat`.
- **`src/Header.tsx`** — remove the `Documents` nav link; leaves
  `Chat` / `Notifications`.

### Manifest / infra

- **`frontend/manifest/remotes.json`** — remove the `"documents"` entry.
- **`frontend/shell/public/remotes.json`**,
  **`frontend/remote-chat/public/remotes.json`**,
  **`frontend/remote-notifications/public/remotes.json`** — remove the
  `"documents"` key from each dev-manifest copy (`remote-documents`'s own
  copy disappears with the directory).
- **`docker-compose.yml`** — remove the `remote-documents:` service
  block and the `- remote-documents` line from `shell`'s `depends_on`.

### Docs

- **`frontend/CONTRACTS.md`** — drop `"documents"` from the manifest
  shape example and the exposed-modules table row; swap the
  `loadRemoteModule` usage example to a surviving remote (e.g. `"chat"`);
  replace the `/chat/:chatId` cross-remote-navigation section (no longer
  cross-remote — upload→chat is now intra-`remote-chat`) with a short
  note on the new `/chat/new` flow, keeping the one fact still load-bearing:
  `POST /chats` is idempotent per `document_id`, which is what makes
  calling it unconditionally after upload safe.
- **`README.md`** — append a new "Phase 14" build-phase entry describing
  the merge (4 domain remotes now, not 5; `/chat/new` owns upload→chat).
  Leave the existing Phase 13 entry as historical record, not rewritten.
- **`docs/architecture.md`** — no changes; it's backend-only (HLD/ER/
  sequence diagrams), no frontend-specific content to update.
- Leave `frontend/BUNDLE_NOTES.md` and
  `docs/superpowers/plans/2026-07-27-frontend-mfe.md` untouched — dated,
  point-in-time artifacts, same convention as not rewriting README's
  Phase 13.

## Build order

1. `remote-chat`: add `ChatNew.tsx`/`.module.css`, extend `types.ts`/
   `api.ts`/`ChatApp.tsx`/`ChatList.tsx`/`ChatList.module.css`.
   Typecheck (`npx tsc --noEmit`).
2. `shell`: update `App.tsx`/`Header.tsx`, delete `DocumentsRoute.tsx`.
   Typecheck.
3. Delete `frontend/remote-documents/`.
4. Update `docker-compose.yml`, `frontend/manifest/remotes.json`, the
   three dev `public/remotes.json` copies.
5. Docs: `CONTRACTS.md`, `README.md`.
6. `docker compose up -d --build shell remote-chat` (remote-documents
   container removed via `docker compose up -d --remove-orphans` or
   explicit `docker compose rm -f remote-documents` after stopping it).

## Verification

- `docker compose ps` shows no `remote-documents` container.
- Visiting `/` redirects to `/chat`, not a 404 or blank `/documents`.
- Header nav shows only Chat / Notifications.
- `/chat` shows the chat list with a "New chat" link; clicking it goes
  to `/chat/new`.
- Submitting `/chat/new` with a title + real PDF uploads, ingests, and
  auto-navigates to `/chat/<uuid>` — same end-to-end behavior verified
  earlier for `DocumentUpload.tsx`, now reachable without a prior trip
  to a separate page.
- `curl http://localhost:3001/documents` (old shell route) no longer
  resolves to anything meaningful — confirms the route is really gone.
