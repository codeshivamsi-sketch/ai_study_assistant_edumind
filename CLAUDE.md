# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack
- Python (Docker images pin `python:3.13-slim`; local interpreter here is 3.14 — see Gotchas)
- FastAPI 0.138 — REST API framework, one service (`core-api`)
- SQLAlchemy 2.0 (async, `Mapped`/`mapped_column` style) + Alembic 1.18 — ORM and migrations, asyncpg driver at runtime, psycopg2 for Alembic
- Celery 5.6 + Redis — wired (broker/backend configured in `worker.py`) but no task is currently registered; ready for a future async job
- structlog — structured JSON logs
- prometheus-fastapi-instrumentator — `/metrics`, scraped by Prometheus, visualized in Grafana
- pytest + pytest-asyncio + httpx `ASGITransport` — tests
- Docker Compose orchestrates postgres, redis, core-api, the celery worker, prometheus, grafana

## Commands
- start everything: `make up`
- stop: `make down`
- logs: `make logs`
- migrate: `cd services/core-api && alembic upgrade head`
- test: `cd services/core-api && pytest tests/ -v`
- single test: `cd services/core-api && pytest tests/test_routes.py::test_document_crud_happy_path -v`
- lint: `ruff check .` (also runs as the PostToolUse hook in `.claude/settings.json`)
- typecheck: none configured — no mypy/pyright in this repo

## Conventions
- Flat modules (`routes.py`, `models.py`, `database.py`, `identity.py`, `base.py`, `main.py`) — no `src/` layout, no package `__init__.py`. Imports are bare (`from routes import router`), so they only resolve when `services/core-api` is the CWD (matches Docker's `WORKDIR /app` and `cd services/core-api` before running locally)
- Every model subclasses the local `base.Base` (`DeclarativeBase`)
- DB access goes through a `get_db()` async generator (in `database.py`) yielding `AsyncSessionLocal()`, injected via FastAPI `Depends` — both `routes.py` and `identity.py` import the same `get_db`, so tests only need to override it in one place
- Identity is a plain `X-User-Id` header, no auth system: `identity.get_current_user` looks the id up in `users` and 401s if it's missing or unknown
- Config is read with `os.getenv(...)` and a localhost default, not a settings module
- New async tests need an explicit `@pytest.mark.asyncio` decorator — `asyncio_mode=auto` is not configured

## Invariants (never violate)
- Ownership checks on `documents`, `quizzes`, and `quiz_attempts` always return **404**, never 403, when a resource exists but isn't the caller's — a resource the caller doesn't own must be indistinguishable from one that doesn't exist
- `quizzes` are reachable only through the `documents` they belong to (`quizzes.document_id → documents.user_id`), and `quiz_attempts` only through the `quizzes` they belong to — every quiz/quiz_attempt endpoint must join back to `documents.user_id` to authorize, not just check the immediate FK
- `quiz_attempts.quiz_id` and `quiz_attempts.user_id` are `ON DELETE RESTRICT`, not `CASCADE` — score history must survive a quiz or user deletion attempt (the delete fails at the DB level instead)

## Tool routing
- Before creating any new function or utility: query codegraph — does it already exist?
- Any non-trivial feature: plan first (Superpowers)

## Decisions
- Document upload (`POST /documents/{id}/upload`) stays synchronous — it calls the agentic service inline and waits, no Celery/async job. Considered and explicitly deferred; revisit only if upload latency becomes a real problem.
- `agentic` was consolidated into this monorepo from a standalone RAG-assistant repo as `services/agentic`, with its own Dockerfile — it listens on host port 8002 because container port 8000 collides with `core-api`'s own 8000.
- Neo4j was added as a new `docker-compose.yml` service because `agentic` has a hard, non-optional dependency on it; `chroma_db/`, the LangGraph SQLite checkpoint, and `uploads/` all get named volumes so on-disk state survives `docker-compose up --build`.

## Gotchas
- This monorepo now runs more than `core-api`: `worker` (Celery), `notifications` (Fastify+gRPC, its own Prisma migrations), and `agentic` (FastAPI+LangGraph, port 8002, Chroma+Neo4j, no Alembic) all live under the root `docker-compose.yml`. `notifications` and `core-api` share the same Postgres database (`edumind`) but manage their own tables through separate migration tools (Prisma vs. Alembic) — one `alembic upgrade head` never covers `notifications`' schema.
- Tests hit a real Postgres (`postgresql+asyncpg://edumind:edumind@localhost:5432/edumind`), not a mock or isolated test DB — `postgres` (at least) must be running via `make up`/`docker-compose up` for `pytest` to pass, and there's no rollback between tests; seeded test users (`alice@edumind.test` / `bob@edumind.test`, fixed UUIDs, see the seed migration) are expected to already exist
- `ruff check .` reports pre-existing `F401` unused-import findings: `base.Base` in `database.py` (imported for side effects, not directly referenced), and the `User`/`Document`/`Quiz`/`QuizAttempt` imports in `migrations/env.py` (imported so `Base.metadata` picks them up for autogenerate, not directly referenced) — the PostToolUse hook will surface these on unrelated edits to those files
- No mypy/pyright configured — nothing enforces the `Mapped[...]` type annotations beyond what SQLAlchemy itself checks at runtime
- `docs/architecture.md` and `docs/blast/` are historical, point-in-time snapshots — the `/arch` and `/blast` commands that generated them were removed upstream; nothing regenerates them automatically anymore
- No per-module READMEs exist yet (e.g. `services/core-api/README.md`) — this repo's root `README.md` is currently the only architecture writeup
