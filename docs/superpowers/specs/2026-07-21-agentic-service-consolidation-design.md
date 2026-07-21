# Consolidate the agentic service into the monorepo — design

## Context

A separate standalone repo, `study_assistant_ai_edumind` (a multi-agent RAG
study assistant: PDF upload → chunking/embeddings → Neo4j knowledge graph →
LangGraph orchestrator with human-in-the-loop quiz evaluation → Claude), is
being folded into this monorepo as `services/agentic`, alongside `core-api`
and `notifications`.

The original request's plan assumed a flat `main.py`/`requirements.txt`
FastAPI app needing only an `OPENAI_API_KEY` and `postgres`/`redis`. The
actual repo is structurally and functionally different — the corrections
below are load-bearing, not stylistic:

- **Wrong LLM provider.** The plan set `OPENAI_API_KEY`; the code
  exclusively uses `ANTHROPIC_API_KEY` (`Anthropic(api_key=os.getenv(...))`
  in `core/config.py`). `OPENAI_API_KEY` would be a dead env var and the
  service would have no working credential at all.
- **Missing hard dependency.** `core/config.py` opens a
  `neo4j.GraphDatabase.driver(...)` at import time — Neo4j is a real
  runtime dependency, not optional, and doesn't exist anywhere in this
  monorepo yet.
- **Port collision.** The app listens on 8000 internally
  (`uvicorn api.main:app --port 8000`) — `core-api` already owns host port
  8000 in this monorepo.
- **The plan's proposed Dockerfile would regress real behavior.** The
  actual `backend/Dockerfile` pre-downloads the `sentence-transformers`
  embedding model at build time and correctly points `CMD` at
  `api.main:app` (not `main:app`, which doesn't exist).
- **Nested nothing.** The service isn't `postgres`/`redis`-dependent at
  all — it uses neither. That assumption in the plan was simply wrong.
- **Structural mismatch.** Everything lives under an extra `backend/`
  subdirectory, alongside the standalone repo's own `docker-compose.yml`,
  `README.md`, and a `docs/` folder of architecture-diagram images — none
  of which map cleanly onto a monorepo that already has its own root
  `docker-compose.yml` and README.

This is very likely the same service as the `edu_mind_ai-backend-1` /
`edu_mind_ai-neo4j-1` containers that have been present on this machine
throughout this project's work, previously treated as unrelated/do-not-touch
during port-8000 conflicts in earlier phases.

## Decisions (confirmed with the user)

- **Add Neo4j** as a new `docker-compose.yml` service — the only way this
  service actually runs.
- **Persist data across rebuilds**: named volumes for ChromaDB
  (`chroma_db/`), the LangGraph SQLite checkpoint file, and `uploads/`
  (uploaded PDFs) — all three are local on-disk state that would otherwise
  reset on every `docker-compose up --build`.
- **Bundle eval dependencies into the runtime image.** `eval/requirements-eval.txt`
  (RAGAs, `datasets`, `langchain-community`) installs alongside
  `requirements.txt` in one image, despite not being needed to actually run
  the service — user's explicit choice over the leaner alternative.
- **Infra-only integration this phase.** `core-api` gets
  `AGENTIC_SERVICE_URL=http://agentic:8000` in its environment; no
  `core-api` code changes. An actual integration endpoint (e.g. a proxy
  route) is out of scope, a future phase.

## Directory structure

Flatten `backend/*` up to be the direct contents of `services/agentic/`,
matching this repo's `services/<name>/` convention (no extra nesting level,
same as `core-api`/`notifications`):

```
services/agentic/
  api/main.py
  core/{config,model,ingest,query,graph}.py
  agents/agents.py
  mcp/server.py
  eval/{run_eval.py,golden_dataset.json,requirements-eval.txt}
  uploads/test_curriculum.pdf
  requirements.txt
  Dockerfile
  .env.example
  README.md
  docs/{langsmith,mcp,neo4j,ragas}.png
```

Dropped, not carried over: the standalone repo's own root-level
`docker-compose.yml` (superseded by this monorepo's root one) and its own
`.gitignore` (superseded by this monorepo's root one — its
project-specific patterns, notably `chroma_db/` and the SQLite checkpoint
file, get added to the root `.gitignore` instead of keeping a second file).
The nested `.git/` from the clone is removed entirely (it's becoming part
of this monorepo's own git history, not a submodule).

`mcp/server.py` (the MCP server exposing tools to Claude Desktop) is
carried over as source but is **not** part of the Docker image's `CMD` or
`docker-compose.yml` — it's a local stdio tool for Claude Desktop
integration, not a network service this compose file runs.

## Dockerfile (`services/agentic/Dockerfile`)

Keeps the real upstream Dockerfile's structure (correct `CMD`, the model
pre-download step) almost unchanged, adding only the eval-deps install:

```dockerfile
FROM python:3.11
WORKDIR /app
COPY requirements.txt eval/requirements-eval.txt ./
COPY eval eval
RUN pip install -r requirements.txt -r eval/requirements-eval.txt
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
COPY . .
RUN mkdir -p /data && rm -f checkpoints.db && ln -s /data/checkpoints.db checkpoints.db
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Container keeps listening on 8000 internally (unchanged from upstream —
minimal diff, easier to compare against upstream later);
`docker-compose.yml` maps host **8002** → container 8000 (revised from an
initial 8001 during implementation — a stale leftover
`python_backend_refresher-ledger-1` container from this repo's own deleted
`ledger` service held that port).

**The `/data` symlink line matters and isn't cosmetic.** `agents/agents.py`
does `sqlite3.connect("checkpoints.db", ...)` — a relative path resolving
to `/app/checkpoints.db` (CWD = `WORKDIR /app`), a single *file*, not a
directory. Named-volume mounts onto a single file are unreliable across
Docker Engine versions and storage/snapshotter backends — some silently
turn the mount target into a directory even when a real file exists there
at image-build time (the original plan's `RUN touch checkpoints.db`
approach assumed this case); others (confirmed during implementation, on a
containerd-snapshotter backend) refuse container creation outright with
`is not directory`. Mounting onto a plain directory is the universally
supported case, so `/data` is a real directory the volume mounts onto, and
`checkpoints.db` becomes a symlink into it — `sqlite3.connect()` follows
the symlink transparently, still with no application code changes (matches
the "no app-logic changes" constraint below — this is a Dockerfile/infra
concern, not application code).

## `docker-compose.yml`

New `neo4j` service:
```yaml
neo4j:
  image: neo4j:latest
  ports:
    - "7475:7474"
    - "7688:7687"
  environment:
    NEO4J_AUTH: neo4j/password
  volumes:
    - neo4j_data:/data
```

(Host ports 7475/7688, not the standard 7474/7687 — an unrelated
already-running `edu_mind_ai-neo4j-1` container held those on the
implementation machine.)

New `agentic` service:
```yaml
agentic:
  build: ./services/agentic
  ports:
    - "8002:8000"
  environment:
    ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
    NEO4J_URI: bolt://neo4j:7687
    NEO4J_USER: neo4j
    NEO4J_PASSWORD: password
    LANGCHAIN_API_KEY: ${LANGCHAIN_API_KEY}
    LANGCHAIN_TRACING_V2: ${LANGCHAIN_TRACING_V2}
    LANGCHAIN_PROJECT: ${LANGCHAIN_PROJECT}
  depends_on:
    - neo4j
  volumes:
    - agentic_chroma:/app/chroma_db
    - agentic_checkpoints:/data
    - agentic_uploads:/app/uploads
```

All three paths are confirmed against the actual source, not guessed:
`chroma_db` (directory — `core/config.py`'s
`chromadb.PersistentClient(path="chroma_db")`) and `uploads` (directory —
`core/ingest.py`'s `os.makedirs("uploads", ...)`) both resolve relative to
`/app` and are directories Docker auto-creates correctly on mount.
`checkpoints.db` (`agents/agents.py`'s `sqlite3.connect("checkpoints.db",
...)`) is the single-file case — mounted via the Dockerfile's `/data`
symlink above rather than at its own path directly, since a container
that mounted a volume straight onto `/app/checkpoints.db` failed to even
start on the implementation machine's Docker Engine.

`core-api` gets one line added to its existing environment block:
`AGENTIC_SERVICE_URL: http://agentic:8000`.

Three new named volumes declared at the bottom:
`neo4j_data`, `agentic_chroma`, `agentic_checkpoints`, `agentic_uploads`.

LangSmith vars are optional — unset means tracing is simply disabled
(LangChain's own no-op behavior), not an error.

## `.gitignore` additions (root)

```
services/agentic/chroma_db/
services/agentic/checkpoints.db
services/agentic/uploads/*
```

`services/agentic/uploads/*` would also match the existing
`test_curriculum.pdf` fixture — but gitignore only affects *untracked*
files, so as long as that one file is explicitly `git add`ed (with `-f`,
since it matches an ignore pattern) when this content first lands in the
monorepo, it stays tracked permanently regardless of the pattern above;
only genuinely new/untracked uploads get ignored going forward.

## Verification

- `docker-compose up --build` — `neo4j` and `agentic` both start; `agentic`
  doesn't crash on the Neo4j driver connection at import time.
- `curl http://localhost:8001/health` → `{"status": "ok"}` — needs no
  credentials.
- `docker exec` into the `agentic` container (or check startup logs) to
  confirm the sentence-transformers model was pre-downloaded at build time,
  not fetched on first request.
- **Out of scope for this phase's automated verification**: `/upload`,
  `/query`, `/agent`, `/evaluate` — all require a real `ANTHROPIC_API_KEY`
  and meaningful PDF content. Manual follow-up once real credentials are
  available.

## What's explicitly out of scope

- No `core-api` code changes beyond the one env var.
- No changes to the agentic service's own application logic — this is a
  lift-and-consolidate, not a refactor.
- No MCP server wiring into docker-compose (it's a local stdio tool, not a
  network service).
- No CI/production credential management — `${ANTHROPIC_API_KEY}` etc. are
  read from the environment/`.env` the same way `${OPENAI_API_KEY}` would
  have been in the original (wrong) plan.
