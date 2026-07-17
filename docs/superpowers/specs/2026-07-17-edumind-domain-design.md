# EduMind study-assistant domain — design

## Context

This repo currently implements a lending domain (`origination` + `ledger`
services, `LoanApplication` + `LedgerEntry` models, shared `creditcore`
Postgres DB). This spec replaces the lending domain entirely with EduMind's
study-assistant domain: users upload documents, generate quizzes from them,
and record quiz attempts.

## Architecture changes

- **Delete `services/ledger/` entirely** — directory, Dockerfile, its own
  Alembic chain (`alembic_version_ledger` table), and its `docker-compose.yml`
  service block. EduMind has no double-entry-bookkeeping equivalent, so
  there's no reason to keep a second service or a shell of one.
- **Rename `services/origination/` → `services/core-api/`.** This becomes
  the one and only service. The `edumind` name belongs to the platform as a
  whole, not to one service — `core-api` is the generic, correct name for
  "the one backend service." Update `docker-compose.yml` build path,
  `Dockerfile` `WORKDIR`, `Makefile` targets/comments, `alembic.ini` paths,
  imports, and any hardcoded `services/origination` references (CLAUDE.md,
  README.md, `docs/architecture.md`).
- **Rename the database**: `creditcore` → `edumind` (db name, user, password
  all become `edumind`) — this stays `edumind` regardless of the service
  rename above, since it's shared platform data, not service-scoped.
  `docker-compose.yml`'s postgres service gets a fresh volume under the new
  name/credentials — old lending tables won't exist there. Connection
  strings in `database.py`, `migrations/env.py`, `tests/test_routes.py`, and
  `docker-compose.yml` all update accordingly.
- **Kafka**: already fully removed from the codebase in a prior commit
  (`0d56fbe removed kafka from project`) — zero Kafka code remains anywhere
  in `services/`. CLAUDE.md, README.md, and `docs/architecture.md` still
  reference it as part of the stack; strip those stale references as part of
  the doc rewrite in this change (no code change needed, docs only).
- **Celery/Redis**: kept wired per approved decision, but the
  `run_credit_check` task is lending-specific and is deleted along with
  `LoanApplication`. `services/core-api/worker.py` keeps the `celery_app`
  config (broker/backend via `REDIS_URL`) with no task defined — ready for a
  future async job (e.g. quiz generation) without inventing one now.
  `docker-compose.yml`'s `worker` and `redis` services are otherwise
  unchanged.
- **Fix the `include_object` bug in `migrations/env.py`**: it currently
  excludes every table except `"ledger_entries"` (a copy-paste leftover from
  the ledger service, called out in CLAUDE.md's existing Gotchas). Remove the
  filter entirely — nothing in this service needs it.

## Data model (`services/core-api/models.py`)

Replaces `LoanApplication`/`LoanStatus` entirely. SQLAlchemy 2.0
`Mapped`/`mapped_column` style, matching the existing service's conventions.

```
users
  id          uuid PK, default gen_random_uuid()
  email       text, unique, indexed
  name        text
  created_at  timestamptz

documents
  id          uuid PK, default gen_random_uuid()
  user_id     uuid FK -> users.id, indexed, ON DELETE CASCADE
  title       text
  status      text, CHECK IN ('uploaded','processing','ready','failed')
  created_at  timestamptz

quizzes
  id           uuid PK, default gen_random_uuid()
  document_id  uuid FK -> documents.id, indexed, ON DELETE CASCADE
  topic        text
  questions    jsonb
  created_at   timestamptz

quiz_attempts
  id          uuid PK, default gen_random_uuid()
  quiz_id     uuid FK -> quizzes.id, indexed, ON DELETE RESTRICT
  user_id     uuid FK -> users.id, indexed, ON DELETE RESTRICT
  answers     jsonb
  score       numeric
  created_at  timestamptz
```

`quiz_attempts` uses `RESTRICT` on both FKs (not `CASCADE`) so score history
survives deletion attempts on quizzes/users — a delete of a quiz or user with
existing attempts must fail at the DB level.

## Identity (`services/core-api/identity.py`)

No auth system — a FastAPI dependency `get_current_user`:
- Reads the `X-User-Id` header.
- 401 if the header is missing.
- Looks the id up in `users`; 401 if no matching row.
- Returns the `User` row on success.

Applied via `Depends` on every route except `GET /health`.

## Endpoints (`services/core-api/routes.py`)

All ownership checks return **404** (never 403) on a resource that exists
but isn't the caller's — cross-user probing must not distinguish "doesn't
exist" from "not yours."

- `POST /documents` — create, owned by caller (`user_id` from `X-User-Id`,
  never from the request body).
- `GET /documents` — list, filtered to `documents.user_id == caller`.
- `GET /documents/{id}` — 404 unless owned by caller.
- `PATCH /documents/{id}` — 404 unless owned by caller.
- `DELETE /documents/{id}` — 404 unless owned by caller.
- `POST /quizzes` — body includes `document_id`; look up the document, 404 if
  missing or not owned by caller, then create the quiz.
- `GET /quizzes` — list, filtered via `quizzes JOIN documents` on
  `documents.user_id == caller`.
- `GET /quizzes/{id}` — join to `documents`, 404 unless owned by caller.
- `PATCH /quizzes/{id}` — same join/404 rule.
- `DELETE /quizzes/{id}` — same join/404 rule.
- `POST /quiz_attempts` — body includes `quiz_id` + `answers` + `score`
  (client-supplied — `questions`/`answers` have no fixed schema, so this
  service stores the score rather than grading it); join
  `quiz_attempts.quiz_id -> quizzes.document_id -> documents.user_id`, 404 if
  the quiz doesn't resolve to a document owned by caller. `user_id` on the
  created row is always the caller's own id from `X-User-Id`, never taken
  from the request body.
- `GET /quizzes/{id}/stats` — same ownership join as quiz GET; 404 on
  someone else's quiz. Returns `{avg_score, attempt_count}` aggregated over
  that quiz's attempts.

No endpoints for `users` (seed-only) or `GET` on `quiz_attempts` directly
(only reachable in aggregate via `/stats`).

## Migrations

- Delete the two existing lending revision files
  (`62dce0f8a9de_create_loan_application_table.py`,
  `0bf1046be179_add_idempotency_key_and_created_at.py`).
- New revision 1 (fresh chain root): `DROP TABLE IF EXISTS loan_applications`
  (defensive, in case someone points this chain at a pre-existing `creditcore`
  DB) + `CREATE TABLE` for `users`, `documents`, `quizzes`, `quiz_attempts`
  with all constraints/indexes/cascades above.
- New revision 2 (seed): insert 2 test users with fixed, known UUIDs/emails
  so tests and manual smoke checks can reference them directly.

## Tests (`services/core-api/tests/test_routes.py`)

Rewritten for the new domain, same real-Postgres + `ASGITransport` pattern
as today (no rollback between tests, requires `make up`'s postgres running):

- Document CRUD happy path, scoped to a seeded user.
- Quiz CRUD happy path, including creating a quiz against another user's
  document → 404.
- `POST /quiz_attempts` happy path + against another user's quiz → 404.
- `GET /quizzes/{id}/stats` happy path (avg score, attempt count) + against
  another user's quiz → 404.
- 401 on missing `X-User-Id` and on an unknown user id.
- 404 on nonexistent ids (documents, quizzes).
- Cross-user access denial across all of the above (2 seeded users; user B
  attempts every operation against user A's resources and gets 404).

## Docs

`CLAUDE.md` (Stack/Commands/Conventions/Invariants/Tool routing/Gotchas
rewritten for the new domain; stale Kafka and lending references removed;
ledger-service invariants replaced with the ownership-scoping invariant),
`README.md`, `docs/architecture.md`, `docker-compose.yml`, `Makefile`,
`alembic.ini` — all updated to match the new service name, DB name, and
domain.

## Verification

`make up` → `alembic upgrade head` → `pytest tests/ -v` all green, plus a
manual curl smoke pass: create via header, cross-user 404 checks, stats
aggregation.
