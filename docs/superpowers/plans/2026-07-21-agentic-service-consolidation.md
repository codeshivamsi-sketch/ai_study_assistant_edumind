# Agentic Service Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fold the standalone `study_assistant_ai_edumind` repo into this monorepo as `services/agentic`, running alongside `core-api` and `notifications` in the same `docker-compose.yml`.

**Architecture:** Clone the external repo, flatten its `backend/` subdirectory up to `services/agentic/` (matching this repo's `services/<name>/` convention), add its two missing pieces of infrastructure (Neo4j, persistent volumes) to `docker-compose.yml`, and verify it starts without requiring real Anthropic credentials (only `/health` is in scope for this phase's automated verification).

**Tech Stack:** FastAPI, LangGraph, ChromaDB, Neo4j, Anthropic Claude, sentence-transformers — all pre-existing in the source being consolidated. No new tech introduced by this plan itself.

## Global Constraints

- The service uses `ANTHROPIC_API_KEY` exclusively — never introduce `OPENAI_API_KEY`, it's not used anywhere in this codebase.
- The service needs neither `postgres` nor `redis` — its only runtime dependency is Neo4j (plus ChromaDB and SQLite, both local files).
- Container listens on port 8000 internally (unchanged from upstream). Host-side port mappings in this plan are **8002** for `agentic` and **7475**/**7688** for `neo4j` (not 8001/7474/7687) — confirmed at plan-writing time that 8001 is held by a stale `python_backend_refresher-ledger-1` container (a leftover from this repo's own deleted `ledger` service, not touched by this plan) and 7474/7687 are held by an unrelated already-running `edu_mind_ai-neo4j-1` container. Re-check port availability with `lsof -nP -iTCP:<port> -sTCP:LISTEN` before assuming these are still free if time has passed.
- No changes to the agentic service's own application logic (`api/`, `core/`, `agents/`, `mcp/`) — this is a lift-and-consolidate. The only file this plan modifies from upstream is the Dockerfile.
- `mcp/server.py` is carried over as source but is not wired into `docker-compose.yml` or the Dockerfile's `CMD` — it's a local stdio tool, not a network service.
- No `core-api` code changes beyond one environment variable (`AGENTIC_SERVICE_URL`) — no proxy endpoint, no integration logic this phase.

---

### Task 1: Clone, restructure, and commit the agentic service source

**Files:**
- Create: `services/agentic/` (entire tree — `api/`, `core/`, `agents/`, `mcp/`, `eval/`, `uploads/test_curriculum.pdf`, `requirements.txt`, `Dockerfile`, `.env.example`, `README.md`, `docs/*.png`)
- Modify: `.gitignore` (root)

**Interfaces:** none (source consolidation only — no code in this task calls into anything else in the monorepo).

- [ ] **Step 1: Clone the external repo to a scratch location**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git clone https://github.com/codeshivamsi-sketch/study_assistant_ai_edumind.git /tmp/agentic_clone_src
```

Expected: clone succeeds, prints the standard `Cloning into '/tmp/agentic_clone_src'...` progress.

- [ ] **Step 2: Verify the expected upstream structure exists**

```bash
find /tmp/agentic_clone_src -maxdepth 2 -type f | sort
```

Expected: includes `backend/Dockerfile`, `backend/requirements.txt`, `backend/.env.example`, `backend/api/main.py` (one level deeper), `README.md`, `docker-compose.yml` (at the clone root — this one is intentionally NOT carried over, see Step 3).

- [ ] **Step 3: Flatten `backend/*` into `services/agentic/`, carry over README + docs, skip the rest**

```bash
mkdir -p services/agentic
cp -r /tmp/agentic_clone_src/backend/. services/agentic/
cp /tmp/agentic_clone_src/README.md services/agentic/README.md
cp -r /tmp/agentic_clone_src/docs services/agentic/docs
rm -rf /tmp/agentic_clone_src
```

This deliberately does NOT carry over the clone's own root-level `docker-compose.yml` or `.gitignore` (superseded by this monorepo's root versions — see Step 5) or its `.git/` (this is becoming part of this monorepo's own history, not a nested repo or submodule).

- [ ] **Step 4: Verify the resulting structure**

```bash
find services/agentic -type f | sort
```

Expected (no `.git`, no `docker-compose.yml`, no `.gitignore` from upstream):
```
services/agentic/.env.example
services/agentic/Dockerfile
services/agentic/README.md
services/agentic/agents/agents.py
services/agentic/api/main.py
services/agentic/core/config.py
services/agentic/core/graph.py
services/agentic/core/ingest.py
services/agentic/core/model.py
services/agentic/core/query.py
services/agentic/docs/langsmith.png
services/agentic/docs/mcp.png
services/agentic/docs/neo4j.png
services/agentic/docs/ragas.png
services/agentic/eval/golden_dataset.json
services/agentic/eval/requirements-eval.txt
services/agentic/eval/run_eval.py
services/agentic/mcp/server.py
services/agentic/requirements.txt
services/agentic/uploads/test_curriculum.pdf
```

- [ ] **Step 5: Add gitignore patterns for the service's runtime state**

Modify `.gitignore` (root) — append:

```

# Agentic service (services/agentic) - runtime state, not source
services/agentic/chroma_db/
services/agentic/checkpoints.db
services/agentic/uploads/*
```

`services/agentic/uploads/*` would also match the `test_curriculum.pdf` fixture already in the tree — that's expected and handled in Step 6 (force-adding that one file so it stays tracked despite the pattern; only genuinely new/untracked uploads get ignored going forward).

- [ ] **Step 6: Stage and commit**

```bash
git add .gitignore
git add services/agentic
git add -f services/agentic/uploads/test_curriculum.pdf
git status --short services/agentic | grep uploads
```

Expected: the status output shows `A  services/agentic/uploads/test_curriculum.pdf` (staged as Added, not silently skipped as ignored) — if it's missing from this output, the `-f` add didn't take and must be re-run before committing.

```bash
git commit -m "feat(agentic): consolidate study_assistant_ai_edumind into services/agentic

Flattened the upstream repo's backend/ subdirectory up to match this
repo's services/<name>/ convention. Dropped the upstream repo's own
docker-compose.yml, .gitignore, and .git (superseded by this
monorepo's root versions / becoming part of this monorepo's own
history). mcp/server.py is carried over as source but not wired into
any service definition - it's a local stdio tool for Claude Desktop,
not a network service."
```

---

### Task 2: Fix the Dockerfile for this monorepo's docker-compose context

**Files:**
- Modify: `services/agentic/Dockerfile`

**Interfaces:**
- Produces: an image whose `CMD` starts the FastAPI app on port 8000 internally, consumed by Task 3's `docker-compose.yml` service definition.

- [ ] **Step 1: Read the current (upstream, unmodified) Dockerfile**

```bash
cat services/agentic/Dockerfile
```

Expected current content:
```dockerfile
FROM python:3.11

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

# Pre-download the model during build
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Modify it — bundle eval dependencies, fix the checkpoint-file volume-mount gotcha**

Replace `services/agentic/Dockerfile`'s entire contents:

```dockerfile
FROM python:3.11

WORKDIR /app

COPY requirements.txt .
COPY eval/requirements-eval.txt eval/requirements-eval.txt
RUN pip install -r requirements.txt -r eval/requirements-eval.txt

# Pre-download the model during build
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

# agents/agents.py does sqlite3.connect("checkpoints.db", ...) - a relative
# path resolving to /app/checkpoints.db (a FILE). Named-volume mounts onto
# a single file are unreliable across Docker Engine versions/snapshotter
# backends (some silently turn the mount target into a directory even
# when a real file exists there at image-build time; on containerd-
# snapshotter backends it can fail container creation outright with
# "is not directory"). Mounting onto a plain directory is the universally
# supported case, so /data is a real directory the volume mounts onto,
# and checkpoints.db becomes a symlink into it - sqlite3.connect()
# follows the symlink transparently and creates the real file inside the
# mounted, persisted directory. No application code changes needed.
RUN mkdir -p /data && rm -f checkpoints.db && ln -s /data/checkpoints.db checkpoints.db

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Two deltas from upstream: the `eval/requirements-eval.txt` copy+install (bundling eval deps into the runtime image, per project decision), and the `/data` symlink (the volume-mount fix — revised from an earlier `RUN touch checkpoints.db` approach after Task 4's verification hit a real container-creation failure on this machine's Docker Engine; see the ledger for the full incident). Everything else — `WORKDIR`, the model pre-download step, `CMD` — is unchanged from upstream.

- [ ] **Step 3: Verify it builds standalone**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
docker build -f services/agentic/Dockerfile -t agentic-test ./services/agentic
```

Expected: build succeeds through all layers, including the `pip install` (both requirements files) and the model pre-download step (will take a minute or two — it downloads a real model from HuggingFace during this step).

- [ ] **Step 4: Verify the checkpoint path is a symlink into a real directory**

```bash
docker run --rm agentic-test ls -la /app/checkpoints.db /data
```

Expected: `/app/checkpoints.db` shows as a symlink (`lrwxr-xr-x ... checkpoints.db -> /data/checkpoints.db`), and `/data` exists as an empty directory.

- [ ] **Step 5: Commit**

```bash
git add services/agentic/Dockerfile
git commit -m "fix(agentic): bundle eval deps, mount checkpoints via a symlinked directory

Named-volume mounts onto a single file are unreliable across Docker
Engine versions - some silently turn the target into a directory,
others (containerd-snapshotter backends) fail container creation
outright with 'is not directory'. /data is a real directory (the
universally-supported mount case); checkpoints.db is a symlink into
it, so sqlite3.connect() in agents.py needs no code changes and still
transparently persists through the mounted volume."
```

---

### Task 3: Wire `docker-compose.yml` — add `neo4j` and `agentic` services

**Files:**
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: `services/agentic/Dockerfile` (Task 2).
- Produces: `neo4j` and `agentic` services reachable within the compose network at `neo4j:7687` and `agentic:8000` respectively — the latter consumed by Task 4's verification and, in a future phase, `core-api`.

- [ ] **Step 1: Replace docker-compose.yml's entire contents**

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: edumind
      POSTGRES_PASSWORD: edumind
      POSTGRES_DB: edumind
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U edumind"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7
    ports:
      - "6379:6379"

  core-api:
    build:
      context: .
      dockerfile: services/core-api/Dockerfile
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    environment:
      DATABASE_URL: postgresql+asyncpg://edumind:edumind@postgres:5432/edumind
      REDIS_URL: redis://redis:6379/0
      NOTIFICATIONS_GRPC_URL: notifications:5001
      AGENTIC_SERVICE_URL: http://agentic:8000
    command: >
      sh -c "alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port 8000"

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

  notifications:
    build:
      context: .
      dockerfile: services/notifications/Dockerfile
    ports:
      - "5000:5000"
      - "5001:5001"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_started
    environment:
      DATABASE_URL: postgresql://edumind:edumind@postgres:5432/edumind
      REDIS_URL: redis://redis:6379/1
      HTTP_PORT: "5000"
      GRPC_PORT: "5001"

  neo4j:
    image: neo4j:latest
    ports:
      - "7475:7474"
      - "7688:7687"
    environment:
      NEO4J_AUTH: neo4j/password
    volumes:
      - neo4j_data:/data

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

  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:latest
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
    depends_on:
      - prometheus

volumes:
  neo4j_data:
  agentic_chroma:
  agentic_checkpoints:
  agentic_uploads:
```

Note `NEO4J_URI: bolt://neo4j:7687` uses the container-internal port (unaffected by the `7688:7687` host remap above — inter-container traffic on the compose network always uses container-internal ports, regardless of how the host side is mapped).

`${ANTHROPIC_API_KEY}`, `${LANGCHAIN_API_KEY}`, `${LANGCHAIN_TRACING_V2}`, `${LANGCHAIN_PROJECT}` are read from the shell environment or a root-level `.env` file if one exists — none are required for this phase's verification scope (Task 4 only checks `/health`), but real usage of `/upload`/`/query`/`/agent`/`/evaluate` needs a real `ANTHROPIC_API_KEY` set.

- [ ] **Step 2: Verify the compose file is valid**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
docker compose config --quiet && echo "valid"
```

Expected: `valid`, no errors.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add neo4j and agentic services to docker-compose.yml

neo4j uses host ports 7475/7688 (not the standard 7474/7687) because
an unrelated already-running edu_mind_ai-neo4j-1 container holds those
on this machine. agentic uses host port 8002 (not 8001) because a
stale python_backend_refresher-ledger-1 container - leftover from
this repo's own deleted ledger service - holds 8001. Both are
verified free at commit time; re-check if this environment has
changed. core-api gets AGENTIC_SERVICE_URL added (infra-only, no code
uses it yet)."
```

---

### Task 4: Full-stack verification

**Files:** none (verification only).

- [ ] **Step 1: Re-check port availability**

```bash
for p in 7475 7688 8002; do
  echo "port $p:"; lsof -nP -iTCP:$p -sTCP:LISTEN 2>/dev/null || echo "  free"
done
```

If any show a listener, stop and report which port and what's using it — don't proceed with a port that's since become occupied by something else.

- [ ] **Step 2: Bring up neo4j and agentic (leave everything else as-is)**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
docker-compose up -d --build neo4j agentic
```

If `core-api`'s own container also needs (re)starting and port 8000 is held by the unrelated `edu_mind_ai-backend-1` container (a known recurring condition on this machine from earlier phases), that's fine — this task only needs `neo4j` and `agentic` running, not the full stack.

- [ ] **Step 3: Confirm both containers are up, not restarting/crash-looping**

```bash
docker ps --filter "name=python_backend_refresher-neo4j-1" --filter "name=python_backend_refresher-agentic-1" --format "{{.Names}}\t{{.Status}}"
```

Expected: both show `Up ...` (not `Restarting` or `Exited`).

- [ ] **Step 4: Confirm /health responds without needing real credentials**

```bash
curl -s -w "\nHTTP %{http_code}\n" http://localhost:8002/health
```

Expected: `{"status":"ok"}` and `HTTP 200`.

- [ ] **Step 5: Confirm the sentence-transformers model was pre-downloaded at build time, not fetched on first request**

```bash
docker exec python_backend_refresher-agentic-1 find / -iname "*MiniLM*" -maxdepth 6 2>/dev/null
```

Expected: at least one path under a cache directory (e.g.
`/root/.cache/torch/sentence_transformers/...` or
`/root/.cache/huggingface/...`) containing `MiniLM` — confirms the model
files are already present in the running container, not something that
would only appear after a real `/upload` request triggers a download.

- [ ] **Step 6: Confirm the checkpoints.db volume-mount fix actually worked**

```bash
docker exec python_backend_refresher-agentic-1 stat /app/checkpoints.db /data
```

Expected: `/app/checkpoints.db` shows type `symbolic link` (pointing at
`/data/checkpoints.db`), and `/data` shows type `directory` — the mounted
volume. If `/app/checkpoints.db` reports `regular file` or the container
failed to start at all with an `is not directory` error, the symlink fix
from Task 2 either wasn't applied or this Docker Engine has a different
variant of the same limitation — stop and report the exact error rather
than guessing further.

- [ ] **Step 7: Confirm Neo4j itself is reachable**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:7475
```

Expected: `200` (Neo4j's browser UI responds) — confirms the host port
remap (7475→7474) is correctly wired, independent of whether `agentic`
can authenticate to it yet.

No commit for this task — verification only. Note explicitly what's out of
scope here: `/upload`, `/query`, `/agent`, `/evaluate` all require a real
`ANTHROPIC_API_KEY` (and, for `/upload`, actual PDF content flowing through
Neo4j + Chroma) — none of that is exercised by this plan's verification.
That's a manual follow-up once real credentials are available.
