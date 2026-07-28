# Frontend contracts

Source of truth for everything duplicated across `frontend/*` apps instead of
shared via a workspace package (see `docs/superpowers/plans/2026-07-27-frontend-mfe.md`
for why). If you change one copy, update this file and every other copy.

## `remotes.json` manifest shape

Fetched at runtime (`fetch('/remotes.json')`), never bundled at build time.

```json
{
  "designSystem": { "url": "http://localhost:3002", "version": "1.0.0" },
  "chat":         { "url": "http://localhost:3004", "version": "1.0.0" },
  "notifications":{ "url": "http://localhost:3005", "version": "1.0.0" }
}
```

Two copies exist, intentionally:
- `frontend/manifest/remotes.json` — canonical, bind-mounted into the
  `shell` Docker container. Editing a `url`/`version` here pins or rolls
  back that one remote with no image rebuild.
- `frontend/<app>/public/remotes.json` — dev-only, points at sibling apps'
  standalone dev-server ports (`3102`-`3105`). Only read when that app runs
  via its own `npm start`.

## Exposed modules per remote

| Remote (federation `name`) | `exposes` |
|---|---|
| `designSystem` | `./Button`, `./TextInput`, `./Card`, `./theme` |
| `chat` | `./ChatApp` |
| `notifications` | `./NotificationsWidget`, `./NotificationsPage` |

## `loadRemoteModule(scope, exposedModule, baseUrl)`

Duplicated verbatim in `shell` + all 3 remotes at `src/utils/loadRemoteModule.ts`.
Injects a `<script>` tag for `${baseUrl}/remoteEntry.js`, then
`container.init(shareScope)` + `container.get(exposedModule)`, and returns
the factory's result directly (`Promise<{ default: Component }>` — call
sites need no adapter, e.g.
`React.lazy(() => loadRemoteModule("chat", "./ChatApp", url))`).

Full implementation lives in the plan doc
(`docs/superpowers/plans/2026-07-27-frontend-mfe.md`) — copy from an
existing app's `utils/loadRemoteModule.ts`, don't retype from memory.

## `edumind:notification` CustomEvent

Duplicated in `remote-chat` (subscribe side) and `remote-notifications`
(dispatch side) at `src/utils/eventBus.ts`.

```ts
export interface EdumindNotificationDetail {
  chatId?: string;
  quizId?: string;
  messageId?: string;
}
```

`chatId`/`quizId` are **independent optional fields, not a discriminated
union** — a notification always has a `chat_id` (an assistant message is
always created on the callback) and may *additionally* carry a `quiz_id`
(quiz created, or a quiz answer graded). An earlier version picked one or
the other by priority (`quiz_id` present → treat as quiz-only, dropping
`chat_id`), which silently broke the chat refresh for quiz creation and
quiz-answer evaluation — neither ever notified `remote-chat` because
nothing subscribed to the quiz-only event shape. Don't reintroduce that
priority check.

`remote-notifications`' `NotificationsWidget` polls
`GET /notifications?user_id=...` every 10s and dispatches this event only
for notifications not present on its *first* poll (first poll seeds a
baseline silently). `remote-chat`'s `ChatDetail` route subscribes and
refetches messages (and quizzes, in case one was just created) whenever
`event.detail.chatId === useParams().chatId` — the URL is the source of
truth for "what's open," not any shared store.

## Upload → chat flow (`/chat/new`)

There is no standalone "Documents" app or destination anymore
(`remote-documents` was retired 2026-07-28 — see
`docs/superpowers/plans/2026-07-28-merge-documents-into-chat.md`).
`ChatList` (`remote-chat`'s `/chat` index route) is the sole landing
page, with a "New chat" link to `/chat/new` (`ChatNew.tsx`). Submitting
that form does everything in one place, entirely within `remote-chat`:
`uploadDocument` (multipart `POST /documents`, atomic create+ingest) →
`createOrGetChat` (`POST /chats`) → `navigate('/chat/' + chat.id)`.

The one fact that still matters here: `POST /chats` is **idempotent per
`document_id`** (`chats.document_id` has a unique index on the backend)
— it returns the existing chat instead of erroring if one already
exists for that document. That's what makes it safe for `ChatNew` to
call `createOrGetChat` unconditionally right after upload with no
"does a chat already exist" check of its own.

## Shared singleton versions (must match across all 4 apps' `package.json`)

```
react:            18.3.1
react-dom:         18.3.1
react-router-dom:  6.26.2
```

Every app's webpack config shares all three as
`{ singleton: true, requiredVersion: pkg.dependencies.<name> }`, including
`designSystem` (which lists `react-router-dom` in `dependencies` even though
it never imports it, purely so the version resolves for the shared block).

## Session/auth prop

Shell owns the only `X-User-Id` value (`SessionContext`, no real login yet).
It's passed to every lazy-loaded remote as an explicit prop, not a shared
React Context:

```ts
interface Session {
  userId: string;
}
```

Each exposed component's top-level prop type includes `session: Session`.

## Webpack/dev-server gotchas (apply to every new app)

Found while building `remote-documents` — apply these to `remote-chat` and
`remote-notifications` too, not just the first remote:

1. **Entry must not synchronously import a shared module.** `src/index.tsx`
   (the webpack `entry`) must be a thin `import("./bootstrap");` — the real
   app code (anything importing `react`, `react-dom`, `react-router-dom`,
   or transitively touching them) goes in `src/bootstrap.tsx`. A synchronous
   import of a shared module in the entry throws `Shared module is not
   available for eager consumption` — the dynamic `import()` is what gives
   webpack's federation runtime an async boundary to initialize the sharing
   scope first. `exposes`-federated modules (e.g. `DocumentsApp.tsx`) don't
   need this split — `container.get()` is already async.
2. **`css-loader`'s `modules` option needs `namedExport: false` explicitly.**
   css-loader v7 changes defaults such that `import styles from
   "*.module.css"` can resolve to `undefined` without it — every
   `.module.css` rule's `css-loader` options must set
   `modules: { namedExport: false, localIdentName: ... }`.
3. **`devServer.headers` needs `"Cross-Origin-Resource-Policy": "cross-origin"`.**
   webpack-dev-server 5.x defaults to `Cross-Origin-Resource-Policy:
   same-origin`, which silently blocks *every other app's* `<script src>`
   load of this app's `remoteEntry.js` (CORP applies to all subresource
   loads, not just `fetch`/XHR like CORS) — every app that's meant to be
   loaded as a remote (i.e. all of them except `shell`) needs this in its
   `devServer` block.
4. **Changes to `webpack.config.js` itself require restarting `npm start`**
   — webpack-dev-server watches source files, not its own config file.
5. **`shell`'s `output.publicPath` must be `"/"`, not `"auto"`.** Shell is
   the page users deep-link directly into (`/chat/<uuid>`, etc.) —
   `"auto"` makes HtmlWebpackPlugin's `<script src="main.js">` resolve
   relative to the current URL path, so a deep link two segments deep
   requests `/chat/main.js` (404/503) instead of `/main.js`. Remotes
   keep `"auto"` — they're loaded cross-origin via `<script>` injection and
   need their chunk URLs relative to their own origin, not shell's current path.
6. **`shell`'s nginx config needs `sendfile off` for `/remotes.json`.** On
   Docker Desktop for Mac (virtiofs bind mounts), nginx's `sendfile` can
   serve a stale/truncated read of a bind-mounted file that was just
   replaced via an atomic rename (which is how most editors/tools write a
   file) — manifested as a JSON parse error on the *next* request after
   editing `frontend/manifest/remotes.json`, even though the file on disk
   was valid. Also set `Cache-Control: no-cache` on this location, or a
   manifest edit only takes effect on a hard refresh instead of a normal
   reload (the browser caches an unversioned JSON response with no
   validators otherwise).
7. **Every app's nginx config needs `Cache-Control: no-cache` on `.js`/`.css`.**
   Chunk filenames are numeric ids (`928.js`, `remoteEntry.js`), not content
   hashes — the same URL can serve different content across image rebuilds.
   Without this, a browser that already loaded an app once keeps serving a
   stale cached bundle after a rebuild/redeploy, sometimes surviving even a
   normal reload — bit us once while iterating on `remote-chat`'s polling
   logic (the container was rebuilt and correct, but the browser kept
   running the old chunk).
