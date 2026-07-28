# Minimal React micro-frontend layer for EduMind

## Context

This is a learning exercise: build a small but complete Module Federation
micro-frontend setup on top of the existing EduMind backend (`services/core-api`,
`services/notifications`), to get hands-on with the mechanics of independently
deployable frontends — dynamic remote loading, singleton shared deps, cross-app
communication without a shared store, CSS isolation, and the operational story
around rolling back one remote independently.

There is currently **no frontend code anywhere in this repo**. Nothing here
replaces or changes backend behavior except two small, additive CORS changes
(currently *zero* CORS config exists on either `core-api` or `notifications`,
which will otherwise hard-block every browser call once a frontend origin
exists).

Scope, confirmed with you: **3 domain remotes**, not 2 — `documents`, `chat`
(covers ask/quiz/summarize + quiz-answer grading), and `notifications` — plus
the shell (host) and a shared `design-system` remote, for 5 federated apps
total. Notifications talks to `remote-chat` via the CustomEvent bus (a new
notification tells an open chat to refetch), which is also the concrete
example for the "no shared store, URL params for shareable state" requirement.
Docker/compose integration is in scope now (your call), matching how every
backend service is already containerized — not deferred.

An `auth` remote is explicitly **out of scope** for this pass, but the shell's
`SessionContext` is structured so one can slot in later without a rewrite (see
below).

## Architecture decisions (binding)

- **Webpack 5 native `container.ModuleFederationPlugin`**, not `@module-federation/enhanced`.
- **No hardcoded `remotes:` entries anywhere.** Every remote load goes through
  a manual dynamic-remote loader (`loadRemoteModule`, inject `<script>` for
  `remoteEntry.js`, `container.init(shareScope)`, `container.get(module)`),
  driven by a runtime-fetched manifest (`remotes.json`), never bundled at
  build time.
- **Two manifest files, intentionally**: `frontend/manifest/remotes.json` is
  canonical and bind-mounted into the `shell` Docker container (editing it —
  URL, version — pins/rolls back one remote with *no image rebuild*, just a
  file edit + browser refresh); each remote's own `public/remotes.json` is a
  small dev-only copy pointing at sibling apps' standalone dev-server ports,
  used only when that remote runs via its own `npm start`.
- **Two port ranges** so a remote's own dev server and its Docker container
  never collide if both happen to be running: canonical/Docker ports
  `3001`–`3005`, standalone dev-server ports `3101`–`3105` (same offset +100).

  | App | Docker (canonical, in `remotes.json`) | Standalone `npm start` |
  |---|---|---|
  | shell | 3001 | 3101 |
  | design-system | 3002 | 3102 |
  | remote-documents | 3003 | 3103 |
  | remote-chat | 3004 | 3104 |
  | remote-notifications | 3005 | 3105 |

- **`react`, `react-dom`, `react-router-dom` are `singleton: true` with
  `requiredVersion` read from each app's own `package.json`** — pin the exact
  same three versions across all 5 apps' `package.json` (independent
  `node_modules` per app, no workspace, so nothing else guarantees they stay
  in sync) to avoid singleton-mismatch warnings.
- **`loadRemoteModule.ts` and `eventBus.ts` are intentionally duplicated**
  (copy-pasted, ~30–40 lines each) into every app that needs them, instead of
  a shared workspace package — keeps every app's build genuinely
  self-contained (no relative cross-imports to sibling folders), which is
  part of what "independently deployable" means here. The wire contract
  (loader signature, event payload shape, `remotes.json` shape, exposed
  module names) is documented once in `frontend/CONTRACTS.md`, which every
  copy must match — mirrors how real cross-team MFEs version a contract
  separately from shared code.
- **Standalone vs. embedded routing**: exposed components (`DocumentsApp`,
  `ChatApp`) render only `<Routes>/<Route>`, never their own
  `<BrowserRouter>` — they assume a Router already exists in the tree. Shell
  provides the single `<BrowserRouter>` when embedded. Each remote's own
  **dev-only** entry (`src/index.tsx`, never federated/exposed, only used by
  that app's own `webpack serve`) wraps the exposed component in its own
  local `<BrowserRouter>` + a hardcoded dev session — this is what makes
  `cd frontend/remote-documents && npm start` a fully working standalone app
  without violating "no nested BrowserRouters" in the composed tree.
- **Session/auth**: shell owns a `SessionContext` (just the `X-User-Id`
  value — matches the backend's actual auth model, no real login). It is
  passed to remotes as an explicit **prop** (`session={{ userId }}`) on the
  lazy-loaded component, not via a shared React Context crossing the
  federation boundary — simpler, no object-identity foot-guns, and is
  literally "auth/user context passed down from shell," not a shared store.
- **Error boundary**: one `RemoteErrorBoundary` (shell-owned) wraps every
  lazy-loaded remote + its `<Suspense>`. Catches both React render errors and
  `loadRemoteModule`'s rejected promise (remoteEntry.js network/404 failure
  — `React.lazy` turns a rejected promise into a thrown error during
  Suspense render, which the boundary catches normally). Retry must force a
  **fresh** `React.lazy()` call (its promise is cached forever per call
  site) via a `nonce` state bump, not just clear the error flag.
- **CSS isolation**: CSS Modules everywhere, `localIdentName` namespaced per
  app (e.g. `documents__[name]__[local]__[hash:base64:5]`) so class names
  never collide once every remote's styles land in one document at runtime.
  No remote imports a global reset — the *only* global CSS in the whole
  system is `shell/src/global.css` (box-sizing reset), applied once at
  shell's own root.
- **Cross-app comm**: `remote-notifications`' persistent bell widget polls
  `GET /notifications?user_id=...` every 10s and dispatches a typed
  `edumind:notification` CustomEvent only for notifications not present on
  its *first* poll (first poll seeds a baseline silently — otherwise every
  page load would replay every historical notification as a "new" event).
  `remote-chat`'s chat-detail route listens for this event and refetches
  messages only if `event.detail.chatId === useParams().chatId` — the URL is
  the source of truth for "what's currently open," no shared store needed.
- **Bundle analyzer**: `webpack-bundle-analyzer` wired into every app behind
  `ANALYZE=true`, static HTML report. Concrete before/after task (not just
  "wire it in and stop") — see Verification.
- **Docker**: each app gets a 2-stage `Dockerfile` (`node:20-alpine` build →
  `nginx:alpine` serve static `dist/`), added as 5 new `docker-compose.yml`
  services. `shell`'s container bind-mounts the canonical `remotes.json` —
  that bind mount *is* the no-rebuild pin/rollback mechanism.
- **Tooling**: TypeScript + `babel-loader` (`@babel/preset-env`,
  `@babel/preset-react` automatic runtime, `@babel/preset-typescript`) —
  faster rebuilds than `ts-loader`; type-checking is a separate
  `tsc --noEmit` script, never in the bundle path. React 18. Plain `npm`, no
  workspaces — every app has its own independent `node_modules`/lockfile.

## Folder structure

```
frontend/
  CONTRACTS.md              # single source of truth every duplicated copy must match
  BUNDLE_NOTES.md           # before/after byte counts (written last)
  manifest/
    remotes.json            # canonical — bind-mounted into shell's container

  design-system/
    package.json  babel.config.js  tsconfig.json  webpack.config.js
    Dockerfile  nginx.conf  public/index.html
    src/
      index.tsx              # dev harness: demo page rendering components directly
      theme.ts
      Button.tsx / Button.module.css
      TextInput.tsx / TextInput.module.css
      Card.tsx / Card.module.css

  remote-documents/
    package.json  babel.config.js  tsconfig.json  webpack.config.js
    Dockerfile  nginx.conf  public/index.html  public/remotes.json   # dev-only, points at *:31xx
    src/
      index.tsx              # dev harness only, own BrowserRouter + mock session
      DocumentsApp.tsx        # exposed: './DocumentsApp'
      api.ts  types.ts
      routes/DocumentList.tsx  DocumentDetail.tsx  DocumentUpload.tsx (+ .module.css each)
      utils/loadRemoteModule.ts  manifest.ts        # duplicated copies

  remote-chat/                # same skeleton as remote-documents
    src/
      index.tsx  ChatApp.tsx   # exposed: './ChatApp'
      api.ts
      routes/ChatList.tsx  ChatDetail.tsx (+.module.css, subscribes to eventBus)  QuizAnswer.tsx  QuizStats.tsx
      utils/loadRemoteModule.ts  manifest.ts  eventBus.ts   # subscribe side

  remote-notifications/       # same skeleton
    src/
      index.tsx
      NotificationsWidget.tsx  # exposed: './NotificationsWidget' — polls + dispatches
      NotificationsPage.tsx    # exposed: './NotificationsPage' — static list, no poll of its own
      NotificationsWidget.module.css
      api.ts
      utils/loadRemoteModule.ts  manifest.ts  eventBus.ts   # dispatch side

  shell/
    package.json  babel.config.js  tsconfig.json  webpack.config.js
    Dockerfile  nginx.conf  public/index.html
    src/
      index.tsx  App.tsx        # BrowserRouter, Routes, SessionProvider, Header
      SessionContext.tsx
      RemoteErrorBoundary.tsx
      Header.tsx                # always mounts NotificationsWidget remote
      global.css                # the one and only global reset in the whole system
      routes/DocumentsRoute.tsx  ChatRoute.tsx  NotificationsRoute.tsx
      utils/loadRemoteModule.ts  manifest.ts
```

Root `.dockerignore` needs `frontend/*/node_modules` and `frontend/*/dist`
added (each Dockerfile's build context is repo root `.`, matching the
existing backend Dockerfiles' convention — without this, a locally-run
`npm start`'s `node_modules`/`dist` would leak into the build context).

## Key implementation (verbatim across copies where noted)

**`utils/loadRemoteModule.ts`** (identical in shell + all 4 remotes):
```ts
// Manual dynamic-remote loader for webpack 5 native container.ModuleFederationPlugin.
// Duplicated verbatim per frontend/CONTRACTS.md — do not import across app folders.

type Container = {
  init(shareScope: unknown): Promise<void> | void;
  get(exposedModule: string): () => Promise<unknown>;
};

declare global {
  interface Window { [scope: string]: Container | undefined }
  function __webpack_init_sharing__(scope: string): Promise<void>;
  var __webpack_share_scopes__: { default: unknown };
}

const loadedEntries = new Set<string>();

function loadScript(entryUrl: string): Promise<void> {
  if (loadedEntries.has(entryUrl)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = entryUrl;
    script.async = true;
    script.onload = () => { loadedEntries.add(entryUrl); resolve(); };
    script.onerror = () => reject(new Error(`Failed to load remoteEntry.js at ${entryUrl}`));
    document.head.appendChild(script);
  });
}

export async function loadRemoteModule<T = { default: unknown }>(
  scope: string,
  exposedModule: string,
  baseUrl: string
): Promise<T> {
  await loadScript(`${baseUrl.replace(/\/$/, "")}/remoteEntry.js`);
  const container = window[scope];
  if (!container) throw new Error(`Remote container "${scope}" missing after loading ${baseUrl}`);
  await __webpack_init_sharing__("default");
  await container.init(__webpack_share_scopes__.default);
  const factory = await container.get(exposedModule);
  return factory() as T;
}
```
Returns `Promise<{default: Component}>`, so call sites need no adapter:
`React.lazy(() => loadRemoteModule("documents", "./DocumentsApp", url))`.

**`utils/eventBus.ts`** (identical in remote-chat + remote-notifications):
```ts
// Typed wrapper around the `edumind:notification` CustomEvent. Duplicated per frontend/CONTRACTS.md.

export type EdumindNotificationDetail =
  | { type: "chat_answer_ready"; chatId: string; messageId?: string }
  | { type: "quiz_ready"; quizId: string; chatId?: string };

const EVENT_NAME = "edumind:notification";

export function dispatchNotificationEvent(detail: EdumindNotificationDetail): void {
  window.dispatchEvent(new CustomEvent<EdumindNotificationDetail>(EVENT_NAME, { detail }));
}

export function subscribeToNotificationEvent(
  handler: (detail: EdumindNotificationDetail) => void
): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<EdumindNotificationDetail>).detail);
  window.addEventListener(EVENT_NAME, listener);
  return () => window.removeEventListener(EVENT_NAME, listener);
}
```

**`RemoteErrorBoundary.tsx`** (shell-owned, one copy):
```tsx
type Props = { children: React.ReactNode; label: string; onRetry: () => void };
type State = { hasError: boolean };

export class RemoteErrorBoundary extends React.Component<Props, State> {
  state: State = { hasError: false };
  static getDerivedStateFromError() { return { hasError: true }; }
  componentDidCatch(error: unknown) { console.error(`[RemoteErrorBoundary] ${this.props.label}:`, error); }
  handleRetry = () => { this.props.onRetry(); this.setState({ hasError: false }); };
  render() {
    if (this.state.hasError) {
      return (
        <div role="alert">
          <p>The {this.props.label} section is temporarily unavailable.</p>
          <button onClick={this.handleRetry}>Retry</button>
        </div>
      );
    }
    return this.props.children;
  }
}
```
Used with a `nonce` driving `useMemo`, so retry actually re-invokes the loader:
```tsx
function DocumentsSection({ manifest, session }) {
  const [nonce, setNonce] = React.useState(0);
  const DocumentsApp = React.useMemo(
    () => React.lazy(() => loadRemoteModule("documents", "./DocumentsApp", manifest.documents.url)),
    [nonce]
  );
  return (
    <RemoteErrorBoundary label="documents" onRetry={() => setNonce((n) => n + 1)}>
      <React.Suspense fallback={<div>Loading documents…</div>}>
        <DocumentsApp session={session} />
      </React.Suspense>
    </RemoteErrorBoundary>
  );
}
```

**Notification poll → dispatch** (in `NotificationsWidget.tsx`), seeding a
baseline on the first poll so pre-existing notifications don't replay as new:
```tsx
const seenIds = React.useRef(new Set<string>());
const firstPoll = React.useRef(true);

async function poll() {
  const data = await fetchNotifications(session.userId);
  if (firstPoll.current) {
    data.forEach((n) => seenIds.current.add(n.id));
    firstPoll.current = false;
  } else {
    for (const n of data) {
      if (!seenIds.current.has(n.id)) {
        seenIds.current.add(n.id);
        dispatchNotificationEvent({ type: n.type, chatId: n.chat_id, quizId: n.quiz_id });
      }
    }
  }
}
// useEffect: const id = setInterval(poll, 10_000); poll(); return () => clearInterval(id);
```

**`remote-documents/webpack.config.js`** (representative remote — exposes,
and separately loads `design-system` at runtime the same way shell does):
```js
const path = require("path");
const HtmlWebpackPlugin = require("html-webpack-plugin");
const { container } = require("webpack");
const { BundleAnalyzerPlugin } = require("webpack-bundle-analyzer");
const pkg = require("./package.json");

module.exports = (_env, argv) => {
  const isProd = argv.mode === "production";
  return {
    entry: "./src/index.tsx", // dev-harness only; DocumentsApp.tsx is the real federation contract
    mode: isProd ? "production" : "development",
    devtool: isProd ? "source-map" : "eval-source-map",
    output: { path: path.resolve(__dirname, "dist"), publicPath: "auto", clean: true },
    resolve: { extensions: [".ts", ".tsx", ".js"] },
    module: {
      rules: [
        { test: /\.tsx?$/, exclude: /node_modules/, use: "babel-loader" },
        {
          test: /\.module\.css$/,
          use: ["style-loader", { loader: "css-loader", options: { modules: { localIdentName: "documents__[name]__[local]__[hash:base64:5]" } } }],
        },
      ],
    },
    devServer: { port: 3103, historyApiFallback: true },
    plugins: [
      new HtmlWebpackPlugin({ template: "./public/index.html" }),
      new container.ModuleFederationPlugin({
        name: "documents",
        filename: "remoteEntry.js",
        exposes: { "./DocumentsApp": "./src/DocumentsApp" },
        shared: {
          react: { singleton: true, requiredVersion: pkg.dependencies.react },
          "react-dom": { singleton: true, requiredVersion: pkg.dependencies["react-dom"] },
          "react-router-dom": { singleton: true, requiredVersion: pkg.dependencies["react-router-dom"] },
        },
      }),
      ...(process.env.ANALYZE === "true"
        ? [new BundleAnalyzerPlugin({ analyzerMode: "static", reportFilename: "report.html", openAnalyzer: false })]
        : []),
    ],
  };
};
```
`shell/webpack.config.js` is the same shape minus `exposes` (its
`ModuleFederationPlugin` exists only to generate the sharing runtime —
`__webpack_init_sharing__`/`__webpack_share_scopes__` — and hold the shared
config) plus one extra global rule for `shell/src/global.css` (`/\.css$/`
excluding `.module.css`), and dev port `3101`.

`design-system` never uses `react-router-dom`, but its `package.json` still
lists it under `dependencies` purely so `pkg.dependencies["react-router-dom"]`
resolves for the shared block — a one-line pragmatic compliance with "all 5
apps declare the same three shared singletons," not worth a special case.

**`babel.config.js`** (identical everywhere):
```js
module.exports = {
  presets: [
    ["@babel/preset-env", { targets: { esmodules: true } }],
    ["@babel/preset-react", { runtime: "automatic" }],
    "@babel/preset-typescript",
  ],
};
```

**`tsconfig.json`** (identical everywhere, `noEmit` — type-checking is a
separate `tsc --noEmit` script):
```json
{
  "compilerOptions": {
    "target": "ES2022", "module": "ESNext", "moduleResolution": "bundler",
    "jsx": "react-jsx", "strict": true, "esModuleInterop": true,
    "skipLibCheck": true, "noEmit": true, "isolatedModules": true
  },
  "include": ["src"]
}
```

**Representative `Dockerfile`** (context is repo root `.`, matching existing backend convention):
```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY frontend/remote-documents/package.json frontend/remote-documents/package-lock.json* ./
RUN npm ci
COPY frontend/remote-documents/ .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/remote-documents/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
```

**`nginx.conf`** (identical across all 5 — remotes don't strictly need SPA
fallback since `remoteEntry.js`/chunks are `<script src>`-loaded not
browser-navigated, but one mental model everywhere costs nothing):
```nginx
server {
  listen 80;
  server_name _;
  root /usr/share/nginx/html;
  location / { try_files $uri /index.html; }
}
```
No CORS headers needed in any frontend nginx config — `<script src>` across
origins isn't subject to CORS (only `fetch`/XHR is); that's handled on the
two backend services below.

## `docker-compose.yml` diff (5 new services)

```yaml
  shell:
    build: { context: ., dockerfile: frontend/shell/Dockerfile }
    ports: ["3001:80"]
    volumes:
      - ./frontend/manifest/remotes.json:/usr/share/nginx/html/remotes.json:ro
    depends_on:
      - design-system
      - remote-documents
      - remote-chat
      - remote-notifications

  design-system:
    build: { context: ., dockerfile: frontend/design-system/Dockerfile }
    ports: ["3002:80"]

  remote-documents:
    build: { context: ., dockerfile: frontend/remote-documents/Dockerfile }
    ports: ["3003:80"]

  remote-chat:
    build: { context: ., dockerfile: frontend/remote-chat/Dockerfile }
    ports: ["3004:80"]

  remote-notifications:
    build: { context: ., dockerfile: frontend/remote-notifications/Dockerfile }
    ports: ["3005:80"]
```
The bind mount on `shell` is the entire "pin/rollback a single remote without
rebuilding" mechanism: edit `./frontend/manifest/remotes.json`'s
`documents.url`/`version`, refresh the browser — no `docker compose build`
or `restart` touches the `shell` image.

## Backend CORS diffs (prerequisite — currently absent on both)

`services/core-api/main.py`:
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import router
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3001", "http://localhost:3002", "http://localhost:3003",
        "http://localhost:3004", "http://localhost:3005",
        "http://localhost:3101", "http://localhost:3103", "http://localhost:3104", "http://localhost:3105",
    ],
    allow_credentials=False,   # no cookies — auth is a bare X-User-Id header
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
Instrumentator().instrument(app).expose(app)
```

`services/notifications/src/main.ts` (register `@fastify/cors`, new dependency):
```ts
import cors from "@fastify/cors";
// ...
export function buildApp() {
  const app = Fastify({ logger: true });
  app.register(cors, {
    origin: [
      "http://localhost:3001", "http://localhost:3005", "http://localhost:3105",
    ],
  });
  app.setErrorHandler(/* unchanged */);
  app.register(registerRoutes);
  return app;
}
```
`package.json`: add `"@fastify/cors": "^10.0.0"`.

Both origin lists include the standalone dev ports (`31xx`) alongside the
canonical Docker ports (`30xx`), since a remote's own dev harness calls the
backend directly from whichever origin it's running at.

## Build order

1. **`design-system`** — package.json/babel/tsconfig/webpack, `theme.ts` +
   `Button`/`TextInput`/`Card` + CSS modules, dev harness. Verify `npm start`
   renders the demo page and `npm run build` emits `dist/remoteEntry.js`.
2. **`shell` skeleton** — routing, `SessionProvider`, `RemoteErrorBoundary`,
   `manifest.ts`, `global.css`, `Header.tsx` (bell mount stubbed with a
   placeholder until step 5). Point one route at a deliberately-broken URL
   first, to prove the error boundary fires before any real remote exists.
3. **`remote-documents` end-to-end** — `DocumentsApp.tsx` + 3 routes +
   `api.ts` hitting core-api, `loadRemoteModule.ts`/`manifest.ts` copies, dev
   harness. Wire the real manifest entry into shell; confirm CSS-module class
   names don't collide with shell's. This is the pattern-proving remote —
   get it fully right before copy-pasting the skeleton for the next two.
4. **`remote-chat`** — copy the proven skeleton, add `ChatApp.tsx` + 4
   routes, `eventBus.ts` subscribe side in `ChatDetail`.
5. **`remote-notifications`** + the cross-remote event — widget/page,
   `eventBus.ts` dispatch side, wire `Header.tsx` to mount the widget for
   real. Manually verify the full loop: widget poll → new notification →
   `chatId` match → `ChatDetail` refetch.
6. **`services/core-api` + `services/notifications` CORS** — small backend
   diffs from above; without these, nothing in steps 3–5 can actually call
   the backend from a browser.
7. **Docker/compose wiring** — 5 Dockerfiles + nginx.conf, root
   `.dockerignore` addition, `docker-compose.yml` diff, canonical
   `frontend/manifest/remotes.json`, the bind mount. `docker compose up
   shell design-system remote-documents remote-chat remote-notifications`.
8. **Bundle-analyzer before/after** (last, needs everything else built) —
   results written into `frontend/BUNDLE_NOTES.md`.

`frontend/CONTRACTS.md` is written alongside step 1 (loader signature, event
payload shape, `remotes.json` shape, exposed module names) and updated as
each later step introduces a new exposed module or event field.

## Verification

**(a) Standalone via each app's own `npm start`:**
`cd frontend/remote-documents && npm start` → `http://localhost:3103`. Its
`src/index.tsx` wraps `DocumentsApp` in its own `<BrowserRouter>` + a
hardcoded dev `X-User-Id` (must match a real row in the `users` table — reuse
one of core-api's seeded test users). Confirm list/detail/upload work
against `core-api` at `localhost:8000` directly — this is only possible once
the CORS diff is in place.

**(b) Hard refresh on a deep link:** with the full `docker compose` stack
up, navigate shell (3001) to `/chat/<uuid>`, hard-refresh. nginx's
`try_files $uri /index.html` serves `index.html` regardless of path, the
router resolves the route client-side, `remote-chat` lazy-loads and renders
that chat — no 404 from nginx.

**(c) Misconfigured remote → error boundary, not white screen:** edit
`frontend/manifest/remotes.json`'s `documents.url` to `http://localhost:9999`,
refresh shell (no rebuild). `loadScript`'s `onerror` rejects, `Suspense`/`lazy`
throws, `RemoteErrorBoundary` shows the fallback + Retry *only* around the
documents section — header, notifications bell, and other routes stay fully
functional.

**(d) Rollback without touching shell's image:** same edit as (c), framed as
pointing `documents` back at a known-good URL/version. Confirm via
`docker compose exec shell cat /usr/share/nginx/html/remotes.json` that the
edit is live immediately, with no `docker compose build shell` or `restart`
run — that's the entire point of the bind mount.

**(e) Bundle analyzer shows real dedup (two measurements, not one):**
   1. Comment out the `shared` block in both `shell/webpack.config.js` and
      `remote-documents/webpack.config.js`, `ANALYZE=true npm run build` in
      both, open each `dist/report.html` — note react+react-dom's size
      appearing in *each* bundle's treemap (a full duplicate copy in both).
   2. Restore `shared`, rebuild both with `ANALYZE=true` again. The real
      proof is at runtime, not in the static report: load the composed
      shell+documents page in a browser, DevTools → Network → JS filter,
      reload, confirm `react`/`react-dom` chunks are fetched **once** total
      (whichever container's copy loads first satisfies the singleton scope
      for both). Record both the analyzer's per-build byte counts and the
      Network tab's total transferred JS for the composed page, before vs.
      after, into `frontend/BUNDLE_NOTES.md`.

`ponytail:` `NotificationsWidget`'s poll is a hardcoded 10s `setInterval`, not
exponential backoff or a websocket/SSE — fine for this exercise's traffic;
upgrade if this ever needs to survive a real rate limit or wants push
instead of poll.
