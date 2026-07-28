# Bundle analysis: what Module Federation's `shared` singleton actually saves

## Method

The naive experiment — comment out `shared` in one app's webpack config,
rebuild, and compare bundle size — doesn't show a meaningful difference.
Every app **always** bundles its own local copy of `react`/`react-dom` as a
fallback module, whether or not `shared` is configured — Module Federation
can't know at build time whether a provider will actually be present at
runtime, so each build stays self-contained. The real saving isn't in what
each build *contains*; it's in what the browser actually *fetches* once
apps are composed on one page. So the measurement here is:

1. Per-build module analysis (`webpack --json`, summing `react`/`react-dom`
   module sizes) — what each app's build *contains*.
2. A live Network-tab trace of the composed page (`shell` embedding
   `remote-documents`) — what the browser actually *fetches*.

## 1. Per-build contents

Both `shell` and `remote-documents` independently bundle their own copy of
react + react-dom as a vendor chunk:

| Build | react module size | react-dom module size | Total |
|---|---|---|---|
| `shell` | 8,063 bytes (source) | 133,751 bytes (source) | 141,814 bytes |
| `remote-documents` | 8,063 bytes (source) | 133,751 bytes (source) | 141,814 bytes |

As minified production assets, `remote-documents`' vendor chunk alone is:

```
assets by chunk 211 KiB (id hint: vendors)
  asset 961.js  130 KiB  [minimized]   — react + scheduler
  asset 648.js   81.8 KiB [minimized]  — react-dom
```

If these were two independently-shipped SPAs with no sharing mechanism at
all, a user visiting both would download **~423 KiB** of react/react-dom
combined (211 KiB × 2, roughly — `shell`'s own copy is similar size) just
from switching between them.

## 2. Live network trace (composed page, `shell` + `remote-documents`)

Loaded `http://localhost:3001/documents` (production Docker build) with a
hard refresh, filtered the Network tab to requests made to `remote-documents`
(`localhost:3003`):

```
GET http://localhost:3003/remoteEntry.js   200
GET http://localhost:3003/928.js           200   (DocumentsApp code + CSS)
GET http://localhost:3003/758.js           200   (small chunk)
```

**`961.js` and `648.js` — the 211 KiB react/react-dom vendor chunk — are never
requested.** `shell` loads its own copy of react/react-dom first (it's the
host, always loaded first); once that copy registers itself in the Module
Federation share scope as satisfying `react@18.3.1`/`react-dom@18.3.1`
(singleton, exact version match), `remote-documents`' federation runtime
sees the requirement is already met and skips fetching its own fallback
chunk entirely. `remote-documents` still executes correctly — it's running
against `shell`'s already-loaded react instance, not its own.

## Result

211 KiB of duplicate JS avoided per additional remote that shares the same
react/react-dom singleton with the host. With three domain remotes
(`documents`, `chat`, `notifications`) all declaring the same shared
singleton versions, a non-federated equivalent (three independent SPAs each
shipping their own react/react-dom) would transfer roughly **3 × 211 KiB ≈
633 KiB** of pure duplication that this setup avoids — on top of the actual
application code, which is genuinely different per remote and isn't
deduplicated (nor should it be).

This is also why `frontend/CONTRACTS.md` insists every app pin the *exact
same* `react`/`react-dom`/`react-router-dom` versions: the singleton match
in the share scope is by `requiredVersion` — a mismatch would make each app
fall back to its own bundled copy, silently losing this saving.
