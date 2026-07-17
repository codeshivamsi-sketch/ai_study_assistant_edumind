# Phase B2 — Notifications service (Node) + gRPC — design

## Context

Phase B2 adds a second, independently-owned service to what has so far been
a single-service (`core-api`) repo: `services/notifications`, built in
Node.js (Fastify + Prisma + Zod) instead of Python. Its purpose is to send a
notification when a quiz is ready, and it needs to talk to `core-api`
across a language boundary — the first cross-service, cross-language
integration in this repo (gRPC), and the first time two different ORMs
(SQLAlchemy/Alembic and Prisma) manage tables in the same shared `edumind`
Postgres database. This phase also doubles as an ecosystem-equivalents
exercise: Fastify≈FastAPI, Prisma≈SQLAlchemy, Zod≈Pydantic, pino≈structlog,
BullMQ≈Celery.

## Language & layout

TypeScript. Fastify/Prisma/Zod are all built and typically consumed as
TS-first tooling (Prisma's generated client and Zod's whole value
proposition are both about types), and it gives typed BullMQ job payloads.

Layout is `src/` + tsc-compiled `dist/` — a deliberate deviation from the
Python services' flat/no-`src/` convention (`routes.py`, `models.py`, ...
directly in the service root), since a TS build needs a source/output
split that a directly-interpreted Python file doesn't.

## Scaffold

`services/notifications/`:
- `package.json` — `fastify`, `@prisma/client` (+ `prisma` dev dep),
  `zod`, `pino`, `bullmq`, `@grpc/grpc-js`, `@grpc/proto-loader`,
  `typescript` (+ `@types/node`) dev dep, `tsx` or plain `tsc && node
  dist/main.js` for run/dev scripts.
- `tsconfig.json` — standard Node18+ target, `src` → `dist`.
- `Dockerfile` — multi-stage: install deps, `tsc` build, run
  `node dist/main.js`.
- `.env.example` — `DATABASE_URL` pointing at the shared `edumind` DB
  (`postgresql://edumind:edumind@postgres:5432/edumind`), `REDIS_URL`
  (`redis://redis:6379/1` — separate DB index from Celery's `/0`),
  `GRPC_PORT` (5001), `HTTP_PORT` (5000).

## Data model — `services/notifications/prisma/schema.prisma`

One model, matching your spec:

```
model Notification {
  id         String   @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  user_id    String   @db.Uuid
  quiz_id    String   @db.Uuid
  message    String
  read       Boolean  @default(false)
  created_at DateTime @default(now())

  @@map("notifications")
}
```

`@default(dbgenerated("gen_random_uuid()"))`, not Prisma's client-side
`uuid()` — matches the DB-generated-ID convention every other table in
this repo already uses.

No `User` model in Prisma — `users` is Alembic's table, not Prisma's.
Generate the migration with `prisma migrate dev --create-only`, then
hand-edit the generated SQL to add
`FOREIGN KEY (user_id) REFERENCES users(id)` (real Postgres FK, just not a
Prisma-declared relation). Runtime command is `prisma migrate deploy`
(non-interactive, never resets) — never `prisma migrate dev` or
`prisma migrate reset` against this shared DB, and never `prisma db pull`
(would introspect and pull Alembic's tables into schema.prisma). This is
the one invariant this phase most needs to not violate; call it out loudly
in code comments in `schema.prisma` and the Dockerfile.

## Identity — `services/notifications/src/identity.ts`

Mirrors `identity.py`: reads `X-User-Id`, 401 if missing. Since there's no
Prisma `User` model, looks the id up via
`prisma.$queryRaw\`SELECT id FROM users WHERE id = ${userId}\`` — 401 if no
row. A Fastify `preHandler` hook, applied to every route.

## Endpoints — `services/notifications/src/routes.ts`

- `POST /notifications` — Zod-validated body `{ user_id, quiz_id, message
  }`; enqueues a `NotifyQuizReady` BullMQ job with that payload; returns
  `202` immediately (job, not the created row — the row doesn't exist yet).
- `GET /notifications?user_id=` — requires `X-User-Id` (401 if
  missing/unknown); 404 unless the query param equals the caller's own id
  (ownership-scoped, same 404-not-403 pattern as `core-api`); returns that
  user's notifications.

## BullMQ job — `services/notifications/src/jobs/notifyQuizReady.ts`

One job type, `NotifyQuizReady`, enqueued from *two* places — the HTTP
handler above and the gRPC handler below — so there's exactly one
notification-row write path with one retry policy (3 attempts, exponential
backoff) regardless of ingress. The processor: insert the `Notification`
row via `prisma.notification.create`; BullMQ's own retry/backoff handles
DB-failure retries, no custom retry loop needed.

## gRPC — `proto/notifications.proto` (repo root, shared source of truth)

```proto
syntax = "proto3";
package notifications;

service NotificationService {
  rpc NotifyQuizReady (NotifyQuizReadyRequest) returns (NotifyQuizReadyResponse);
}

message NotifyQuizReadyRequest {
  string user_id = 1;
  string quiz_id = 2;
}

message NotifyQuizReadyResponse {
  bool accepted = 1;
}
```

- **Node (server)**: `@grpc/proto-loader` loads this file *dynamically at
  startup* — no codegen step, no generated files to go stale. Server binds
  `0.0.0.0:5001`. Handler builds a default message (e.g. `"Your quiz is
  ready!"`), enqueues the same `NotifyQuizReady` BullMQ job as the HTTP
  path, responds `{ accepted: true }`.
- **Python (client)**: no equivalent dynamic-loading idiom in idiomatic
  Python gRPC, so `core-api` gets real generated stubs via `grpcio-tools`
  (`python -m grpc_tools.protoc`). Not checked in — generated by a `make
  proto` target, run at Docker build time from the same root `proto/`
  file, so there's one source of truth either way.
- `core-api`'s `requirements.txt` gains `grpcio` + `grpcio-tools`.

## Trigger — `services/core-api/routes.py::create_quiz`

Right after the existing `await db.commit()` / `await db.refresh(quiz)` in
`create_quiz`, call the generated gRPC stub's `NotifyQuizReady(user_id=...,
quiz_id=...)` against `notifications:5001`. Fire-and-log, not
fire-and-forget-silently: a gRPC failure logs via the existing `structlog`
`log` and does not fail the quiz-creation request (notification delivery
is best-effort, quiz creation is the source of truth).

## docker-compose.yml

New `notifications` service: `build: ./services/notifications`, ports
`5000:5000` and `5001:5001`, `depends_on: postgres (healthy), redis`,
env `DATABASE_URL`/`REDIS_URL`/`GRPC_PORT`/`HTTP_PORT`, command runs
`prisma migrate deploy` then starts the compiled server. No custom Docker
network needed — Compose's default network already resolves service names
(`notifications`, `postgres`, `redis`) exactly like `core-api` already
resolves `postgres`/`redis` today. `core-api`'s environment gains
`NOTIFICATIONS_GRPC_URL=notifications:5001`.

## Tests — `services/notifications/test/routes.test.ts`

`node:test` + Fastify `app.inject()` (in-process, no real server bound —
the Node equivalent of `httpx.ASGITransport`), against the real `edumind`
Postgres (same "no mocks, hits a real DB" convention as the Python tests):
- `POST /notifications` happy path → `202`.
- `GET /notifications?user_id=` happy path for the caller's own id.
- `401` on missing/unknown `X-User-Id`.
- `404` on `user_id` query param that doesn't match the caller.

## Docs

Not touched in this phase — README/CLAUDE.md/architecture updates now go
through `/docs-sync` on request, per the upstream workflow sync earlier
in this project, not as an automatic part of every feature task.

## Verification

`docker-compose up --build` brings up `notifications` alongside the
existing services; `prisma migrate deploy` applies the FK-patched
migration against `edumind`; `node --test` (or the equivalent npm script)
green in `services/notifications`; existing `core-api` `pytest` suite
still green; manual check: `POST /quizzes` on `core-api` triggers the gRPC
call, a row appears in `notifications` after the BullMQ job runs, and
`GET /notifications?user_id=<owner>` returns it while a different caller's
id 404s.
