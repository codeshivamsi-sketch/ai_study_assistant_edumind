# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Stack
- Python (Docker images pin `python:3.13-slim`; local interpreter here is 3.14 — see Gotchas)
- FastAPI 0.138 — REST API framework, one independent app per service
- SQLAlchemy 2.0 (async, `Mapped`/`mapped_column` style) + Alembic 1.18 — ORM and migrations, asyncpg driver at runtime, psycopg2 for Alembic
- Celery 5.6 + Redis — async credit-check job (origination only)
- aiokafka — publishes/consumes the `loan.submitted` event (KRaft-mode Kafka, no Zookeeper)
- structlog (origination only) — structured JSON logs
- prometheus-fastapi-instrumentator — `/metrics` on both services, scraped by Prometheus, visualized in Grafana
- pytest + pytest-asyncio + httpx `ASGITransport` — tests (origination only)
- Docker Compose orchestrates postgres, redis, kafka, both services, the celery worker, prometheus, grafana

## Commands
- start everything: `make up`
- stop: `make down`
- logs: `make logs`
- migrate origination: `cd services/origination && alembic upgrade head`
- migrate ledger: `cd services/ledger && alembic upgrade head`
- test (origination — the only service with tests): `cd services/origination && pytest tests/ -v`
- single test: `cd services/origination && pytest tests/test_routes.py::test_idempotency -v`
- lint: `ruff check .` (also runs as the PostToolUse hook in `.claude/settings.json`)
- typecheck: none configured — no mypy/pyright in this repo

## Conventions
- Flat per-service modules (`routes.py`, `models.py`, `database.py`, `base.py`, `main.py`) — no `src/` layout, no package `__init__.py`. Imports are bare (`from routes import router`), so they only resolve when the service directory is the CWD (matches Docker's `WORKDIR /app` and `cd services/<service>` before running locally)
- Each service owns its own FastAPI app, models, and Alembic migration chain, fully independent of the other
- Every model subclasses that service's local `base.Base` (`DeclarativeBase`) — there is no shared base between services
- DB access goes through a `get_db()` async generator yielding `AsyncSessionLocal()`, injected via FastAPI `Depends`
- Config is read with `os.getenv(...)` and a localhost default, not a settings module
- New async tests need an explicit `@pytest.mark.asyncio` decorator — `asyncio_mode=auto` is not configured

## Invariants (never violate)
- Origination and Ledger share one Postgres database (`creditcore`). Ledger's Alembic env overrides `version_table="alembic_version_ledger"` specifically so its migration history doesn't collide with Origination's default `alembic_version` table — don't remove that override or point both at the same version table
- `POST /applications` idempotency depends on the unique `idempotency_key` column: a duplicate key must return the existing row, never create a second one
- Every loan submission must produce a matching debit + credit `LedgerEntry` pair (double-entry bookkeeping) — never write one leg without the other

## Tool routing
- Before creating any new function or utility: query codegraph — does it already exist?
- Before refactoring anything shared: run /blast on the affected files
- Any non-trivial feature: plan first (Superpowers)

## Where the "why" lives
- Decisions: `docs/adr/` — read before refactoring anything structural
- Architecture map: `docs/architecture.md` (regenerate with /arch)
- Blast-radius snapshots: `docs/blast/`
- Module intent: `services/<service>/README.md` (none exist yet — this repo's README.md at the root is currently the only architecture writeup)

## Gotchas
- **Kafka does not connect Origination and Ledger, despite what the README's diagram shows.** Ledger has zero Kafka code or dependency. Origination publishes `loan.submitted` and also consumes it itself (`group_id="origination-group"`), but the consumer only logs the message — it doesn't call Ledger. Ledger entries are created solely by direct `POST /postings` calls. Don't assume the event wires anything together; see `docs/architecture.md` for the verified data flow
- `services/origination/migrations/env.py` has an `include_object` filter that excludes every table except `"ledger_entries"` — this appears copy-pasted from the ledger service and will silently drop `loan_applications` from `alembic revision --autogenerate` in origination. Fix or remove before relying on autogenerate there
- Only origination has tests (`services/origination/tests/test_routes.py`); ledger has zero coverage
- Tests hit a real Postgres (`postgresql+asyncpg://creditcore:creditcore@localhost:5432/creditcore`), not a mock or isolated test DB — `postgres` (at least) must be running via `make up`/`docker-compose up` for `pytest` to pass, and there's no rollback between tests
- `ruff check .` currently reports 5 pre-existing `F401` unused-import findings (e.g. unused `base.Base` imports in both `database.py` files, unused model imports in both `migrations/env.py` files) — the new PostToolUse hook will surface these on unrelated edits to those files
- No mypy/pyright configured — nothing enforces the `Mapped[...]` type annotations beyond what SQLAlchemy itself checks at runtime
