# Notifications Service (Phase B2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `services/notifications` (Node/TypeScript: Fastify + Prisma + Zod + BullMQ) as a second, independent service, wired to `core-api` (Python) over gRPC, sharing the `edumind` Postgres database with Alembic.

**Architecture:** One new Node service with its own Fastify HTTP API, a Prisma-managed `notifications` table (FK to Alembic's `users` table added by hand, not via a Prisma relation), a BullMQ job fed by both its HTTP `POST /notifications` route and a gRPC `NotifyQuizReady` handler, and a `core-api` change that calls that gRPC method after quiz creation. Both services' Docker builds move to a repo-root context so they can `COPY` the shared `proto/notifications.proto`.

**Tech Stack:** Fastify 5, `@prisma/client`/`prisma` 6, Zod 3, pino 9, BullMQ 5 + ioredis, `@grpc/grpc-js` + `@grpc/proto-loader` (Node, dynamic proto loading, no codegen), `grpcio`/`grpcio-tools` (Python, generated stubs), TypeScript 5, `node:test` (built-in test runner).

## Global Constraints

- Shared DB is `edumind` (Postgres 16, already running via `docker-compose`'s `postgres` service) — every write in this plan lands there.
- **Never run `prisma migrate dev` (in any form, including `--create-only`) or `prisma db pull` against this database.** `migrate dev`'s drift check diffs the whole `public` schema against Prisma's migration history and offers an interactive reset the first time it sees Alembic's tables — `--create-only` does not skip that check. Migration folders/files are hand-written directly (see Task 3). The only two Prisma commands ever run against this DB are `prisma migrate resolve --applied <name>` (marks a migration applied without executing its SQL — used once, to baseline Prisma's history against Alembic's pre-existing tables) and `prisma migrate deploy` (applies pending migrations, no drift detection).
- Prisma's `schema.prisma` models `Notification` only — never add a Prisma `User` model or any `@relation` into `users`.
- `notifications.user_id`'s Postgres FK is hand-written SQL in the generated migration, not a Prisma-declared relation.
- All ownership checks return `404`, never `403` — same invariant `core-api` already established (see `CLAUDE.md`).
- `proto/notifications.proto` (repo root) is the single source of truth for the gRPC contract — Node loads it dynamically at runtime, Python generates stubs from it (never hand-edit generated Python stub files).
- Redis: reuse the existing `redis` container, BullMQ on DB index `1` (`redis://redis:6379/1`) — Celery already owns index `0`.
- The gRPC call from `core-api` to `notifications` is best-effort: a failure must never fail the `POST /quizzes` request.

---

### Task 1: gRPC contract + Python codegen tooling

**Files:**
- Create: `proto/notifications.proto`
- Modify: `Makefile` (add `proto` target)
- Modify: `services/core-api/requirements.txt` (add `grpcio`, `grpcio-tools`)
- Modify: `.gitignore` (ignore generated Python stubs)

**Interfaces:**
- Produces: the `NotificationService.NotifyQuizReady(NotifyQuizReadyRequest{user_id, quiz_id}) -> NotifyQuizReadyResponse{accepted}` gRPC contract, consumed by Task 7 (Node server) and Task 9 (Python client).

- [ ] **Step 1: Write the proto file**

Create `proto/notifications.proto`:

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

- [ ] **Step 2: Add the `proto` Makefile target**

Modify `Makefile` — add at the end:

```makefile

proto:
	python3 -m grpc_tools.protoc -I proto --python_out=services/core-api --grpc_python_out=services/core-api proto/notifications.proto
```

- [ ] **Step 3: Add grpcio deps to core-api's requirements**

Modify `services/core-api/requirements.txt` — append:

```
grpcio==1.68.0
grpcio-tools==1.68.0
```

- [ ] **Step 4: Ignore generated Python stubs**

Modify `.gitignore` — add a new section:

```

# Generated gRPC stubs (regenerate with `make proto`)
services/core-api/notifications_pb2.py
services/core-api/notifications_pb2_grpc.py
```

- [ ] **Step 5: Verify codegen works**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
python3 -m venv /tmp/notif_verify_venv
source /tmp/notif_verify_venv/bin/activate
pip install -q grpcio==1.68.0 grpcio-tools==1.68.0
make proto
python3 -c "
import sys
sys.path.insert(0, 'services/core-api')
import notifications_pb2
req = notifications_pb2.NotifyQuizReadyRequest(user_id='u1', quiz_id='q1')
print(req)
"
deactivate
rm -rf /tmp/notif_verify_venv
```

Expected: prints the request message (`user_id: "u1"\nquiz_id: "q1"\n`) with no errors, and `services/core-api/notifications_pb2.py` + `services/core-api/notifications_pb2_grpc.py` now exist.

- [ ] **Step 6: Commit**

```bash
git add proto/notifications.proto Makefile services/core-api/requirements.txt .gitignore
git commit -m "feat(notifications): add gRPC contract and Python codegen tooling"
```

---

### Task 2: Node service scaffold

**Files:**
- Create: `services/notifications/package.json`
- Create: `services/notifications/tsconfig.json`
- Create: `services/notifications/src/logger.ts`
- Modify: `.gitignore` (ignore Node build artifacts)

**Interfaces:**
- Produces: `logger` (a `pino.Logger` instance) exported from `src/logger.ts`, consumed by every later Node task.

- [ ] **Step 1: Write package.json**

Create `services/notifications/package.json`:

```json
{
  "name": "notifications",
  "version": "1.0.0",
  "private": true,
  "scripts": {
    "copy-proto": "mkdir -p proto && cp ../../proto/notifications.proto proto/notifications.proto",
    "build": "npm run copy-proto && npx prisma generate && tsc",
    "start": "node dist/src/main.js",
    "test": "npm run build && node --test dist/test"
  },
  "dependencies": {
    "@grpc/grpc-js": "^1.11.0",
    "@grpc/proto-loader": "^0.7.13",
    "@prisma/client": "^6.1.0",
    "bullmq": "^5.28.0",
    "fastify": "^5.1.0",
    "ioredis": "^5.4.1",
    "pino": "^9.5.0",
    "zod": "^3.23.8"
  },
  "devDependencies": {
    "@types/node": "^22.9.0",
    "prisma": "^6.1.0",
    "typescript": "^5.6.3"
  }
}
```

- [ ] **Step 2: Write tsconfig.json**

Create `services/notifications/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "CommonJS",
    "moduleResolution": "node",
    "outDir": "dist",
    "rootDir": ".",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "resolveJsonModule": true
  },
  "include": ["src/**/*.ts", "test/**/*.ts"]
}
```

- [ ] **Step 3: Write the shared logger**

Create `services/notifications/src/logger.ts`:

```typescript
import pino from "pino";

export const logger = pino({ name: "notifications" });
```

- [ ] **Step 4: Ignore Node build artifacts**

Modify `.gitignore` — add:

```

# Node (services/notifications)
services/notifications/node_modules/
services/notifications/dist/
services/notifications/proto/
services/notifications/generated/
```

- [ ] **Step 5: Install and verify**

```bash
cd services/notifications
npm install
npx tsc --noEmit
```

Expected: `npm install` succeeds, `tsc --noEmit` reports no errors (only `src/logger.ts` exists so far — trivially valid).

- [ ] **Step 6: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/notifications/package.json services/notifications/package-lock.json services/notifications/tsconfig.json services/notifications/src/logger.ts .gitignore
git commit -m "feat(notifications): scaffold Node/TypeScript service"
```

---

### Task 3: Prisma schema + migration against the shared DB

**Files:**
- Create: `services/notifications/prisma/schema.prisma`
- Create: `services/notifications/.env` (local only, not committed — see Step 3)
- Create: `services/notifications/.env.example`
- Modify: `services/notifications/prisma/migrations/<timestamp>_create_notifications/migration.sql` (generated, then hand-edited)

**Interfaces:**
- Produces: the `notifications` table in the `edumind` DB (`id`, `user_id`, `quiz_id`, `message`, `read`, `created_at`), consumed by Task 4 (identity) and Task 5 (job processor).

- [ ] **Step 1: Write the Prisma schema**

Create `services/notifications/prisma/schema.prisma`:

```prisma
// This schema owns ONLY the `notifications` table. Do not add a `User`
// model or any relation into `users` — that table belongs to core-api's
// Alembic migrations. Never run `prisma migrate reset` or `prisma db pull`
// against this database; both would destroy or corrupt Alembic's tables.

generator client {
  provider = "prisma-client-js"
}

datasource db {
  provider = "postgresql"
  url      = env("DATABASE_URL")
}

model Notification {
  id         String   @id @default(dbgenerated("gen_random_uuid()")) @db.Uuid
  user_id    String   @db.Uuid
  quiz_id    String   @db.Uuid
  message    String
  read       Boolean  @default(false)
  created_at DateTime @default(now())

  @@index([user_id])
  @@map("notifications")
}
```

- [ ] **Step 2: Write .env.example**

Create `services/notifications/.env.example`:

```
DATABASE_URL=postgresql://edumind:edumind@localhost:5432/edumind
REDIS_URL=redis://localhost:6379/1
HTTP_PORT=5000
GRPC_PORT=5001
NODE_ENV=development
```

- [ ] **Step 3: Create a local .env for migration generation**

```bash
cd services/notifications
cp .env.example .env
```

(`.env` is already covered by the root `.gitignore`'s existing `.env` entry — do not commit it.)

- [ ] **Step 4: Hand-create the migration folder and file (do not use `prisma migrate dev`)**

Requires `postgres` running: `docker-compose up -d postgres` from the repo root if it isn't already up.

**Do not run `prisma migrate dev` (with or without `--create-only`) against this database.** Its drift check diffs the *entire* `public` schema against Prisma's (empty) migration history on the very first run — since Alembic's tables (`users`, `documents`, `quizzes`, `quiz_attempts`, `alembic_version`) are invisible to that history, Prisma classifies all of them as drift and offers an interactive schema reset ("You may use prisma migrate reset... All data will be lost"). `--create-only` does not skip this check — the check runs before the create-only migration is even generated. `prisma migrate deploy` (Step 6) does not run drift detection at all, so it's the only command from this family that's safe here.

Create the migration folder by hand, using today's date/time as the
timestamp prefix in Prisma's `YYYYMMDDHHMMSS_<name>` convention (run
`date +%Y%m%d%H%M%S` to get it, never guess it):

```bash
cd services/notifications
mkdir -p "prisma/migrations/$(date +%Y%m%d%H%M%S)_create_notifications"
```

Note the exact folder name you created — you need it for the next step.

- [ ] **Step 5: Write the migration SQL directly**

Create `prisma/migrations/<timestamp>_create_notifications/migration.sql` (the folder from Step 4) with:

```sql
-- CreateTable
CREATE TABLE "notifications" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "user_id" UUID NOT NULL,
    "quiz_id" UUID NOT NULL,
    "message" TEXT NOT NULL,
    "read" BOOLEAN NOT NULL DEFAULT false,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "notifications_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "notifications_user_id_idx" ON "notifications"("user_id");

-- AddForeignKey (hand-written: users is Alembic's table, not Prisma's —
-- see the warning in schema.prisma)
ALTER TABLE "notifications" ADD CONSTRAINT "notifications_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
```

- [ ] **Step 6: Baseline Prisma's migration history before deploying**

`prisma migrate deploy` refuses to run against a database that already
has schema objects but no `_prisma_migrations` bookkeeping table yet
(error `P3005`, "the database schema is not empty") — this DB has
Alembic's five tables and no Prisma history. This is Prisma's documented
baselining case for adopting Prisma against an existing database
(https://pris.ly/d/migrate-baseline): mark a no-op placeholder migration
as already-applied so Prisma's history has a starting point, without
running any SQL against the database.

```bash
cd services/notifications
mkdir -p prisma/migrations/00000000000000_baseline
echo "-- baseline: pre-existing schema (Alembic's tables), not managed by Prisma" > prisma/migrations/00000000000000_baseline/migration.sql
npx prisma migrate resolve --applied 00000000000000_baseline
```

Expected: `Migration 00000000000000_baseline marked as applied.` —
`migrate resolve --applied` only inserts a bookkeeping row into
`_prisma_migrations`; it does not execute the migration's SQL, so the
placeholder file's contents don't matter beyond documenting why it
exists. The `00000000000000` prefix guarantees it always sorts before
every real migration.

- [ ] **Step 7: Apply the migration**

```bash
cd services/notifications
npx prisma migrate deploy
```

Expected output includes `1 migration found... Applied` (the baseline
from Step 6 is already resolved, so only `create_notifications` applies).

- [ ] **Step 8: Verify the table and FK**

```bash
docker exec python_backend_refresher-postgres-1 psql -U edumind -d edumind -c "\d notifications"
```

Expected: shows columns `id, user_id, quiz_id, message, read, created_at`, index `notifications_user_id_idx`, and `FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE`.

- [ ] **Step 9: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/notifications/prisma services/notifications/.env.example
git commit -m "feat(notifications): add Prisma schema and notifications table migration"
```

---

### Task 4: Prisma client + identity check (with test)

**Files:**
- Create: `services/notifications/src/db.ts`
- Create: `services/notifications/src/identity.ts`
- Create: `services/notifications/test/identity.test.ts`

**Interfaces:**
- Consumes: `notifications` table + `users` table (Task 3), `logger` (Task 2).
- Produces: `prisma` (a `PrismaClient` instance, `src/db.ts`) and `requireUser` (a Fastify `preHandler`, `src/identity.ts`, sets `request.user = { id }` or replies `401`) — both consumed by Task 5 and Task 6.

- [ ] **Step 1: Write the Prisma client module**

Create `services/notifications/src/db.ts`:

```typescript
import { PrismaClient } from "@prisma/client";

export const prisma = new PrismaClient();
```

- [ ] **Step 2: Write the failing test**

Create `services/notifications/test/identity.test.ts`:

```typescript
import { test } from "node:test";
import assert from "node:assert/strict";
import Fastify from "fastify";
import { requireUser } from "../src/identity";

const ALICE_ID = "11111111-1111-1111-1111-111111111111";
const UNKNOWN_ID = "99999999-9999-9999-9999-999999999999";

function buildTestApp() {
  const app = Fastify();
  app.addHook("preHandler", requireUser);
  app.get("/whoami", async (request) => ({ id: request.user!.id }));
  return app;
}

test("requireUser accepts a known X-User-Id and sets request.user", async () => {
  const app = buildTestApp();
  const response = await app.inject({
    method: "GET",
    url: "/whoami",
    headers: { "x-user-id": ALICE_ID },
  });
  assert.equal(response.statusCode, 200);
  assert.deepEqual(response.json(), { id: ALICE_ID });
});

test("requireUser returns 401 when X-User-Id header is missing", async () => {
  const app = buildTestApp();
  const response = await app.inject({ method: "GET", url: "/whoami" });
  assert.equal(response.statusCode, 401);
});

test("requireUser returns 401 for an unknown user id", async () => {
  const app = buildTestApp();
  const response = await app.inject({
    method: "GET",
    url: "/whoami",
    headers: { "x-user-id": UNKNOWN_ID },
  });
  assert.equal(response.statusCode, 401);
});

test("requireUser returns 401 for a malformed user id", async () => {
  const app = buildTestApp();
  const response = await app.inject({
    method: "GET",
    url: "/whoami",
    headers: { "x-user-id": "not-a-uuid" },
  });
  assert.equal(response.statusCode, 401);
});
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd services/notifications
npm run build
```

Expected: FAIL — `tsc` errors because `src/identity.ts` doesn't exist yet (`Cannot find module '../src/identity'`).

- [ ] **Step 4: Write the implementation**

Create `services/notifications/src/identity.ts`:

```typescript
import type { FastifyRequest, FastifyReply } from "fastify";
import { prisma } from "./db";

declare module "fastify" {
  interface FastifyRequest {
    user?: { id: string };
  }
}

export async function requireUser(request: FastifyRequest, reply: FastifyReply) {
  const userId = request.headers["x-user-id"];

  if (!userId || Array.isArray(userId)) {
    return reply.code(401).send({ error: "X-User-Id header is required" });
  }

  let rows: { id: string }[];
  try {
    rows = await prisma.$queryRaw<{ id: string }[]>`SELECT id FROM users WHERE id = ${userId}::uuid`;
  } catch {
    return reply.code(401).send({ error: "Unknown user" });
  }

  if (rows.length === 0) {
    return reply.code(401).send({ error: "Unknown user" });
  }

  request.user = { id: rows[0].id };
}
```

- [ ] **Step 5: Run test to verify it passes**

Requires the `edumind` DB seeded with Alice/Bob (from `services/core-api`'s seed migration — already applied if you've run `alembic upgrade head` there per the earlier phase).

```bash
cd services/notifications
export DATABASE_URL="postgresql://edumind:edumind@localhost:5432/edumind"
npm test
```

Expected: all 4 tests in `identity.test.ts` pass.

- [ ] **Step 6: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/notifications/src/db.ts services/notifications/src/identity.ts services/notifications/test/identity.test.ts
git commit -m "feat(notifications): add Prisma client and X-User-Id identity check"
```

---

### Task 5: BullMQ queue + job processor (with test)

**Files:**
- Create: `services/notifications/src/queue.ts`
- Create: `services/notifications/src/jobs/notifyQuizReady.ts`
- Create: `services/notifications/test/notifyQuizReady.test.ts`

**Interfaces:**
- Consumes: `prisma` (Task 4), `logger` (Task 2).
- Produces: `enqueueNotifyQuizReady(payload: NotifyQuizReadyPayload): Promise<Job>` and `NotifyQuizReadyPayload { user_id: string; quiz_id: string; message: string }` (`src/queue.ts`) — consumed by Task 6 (routes) and Task 7 (gRPC server). `startNotifyQuizReadyWorker(): Worker` (`src/jobs/notifyQuizReady.ts`) — consumed by Task 6's `main.ts` wiring.

- [ ] **Step 1: Write the queue module**

Create `services/notifications/src/queue.ts`:

```typescript
import { Queue } from "bullmq";
import IORedis from "ioredis";

export const connection = new IORedis(process.env.REDIS_URL ?? "redis://localhost:6379/1", {
  maxRetriesPerRequest: null,
});

export const NOTIFY_QUIZ_READY_QUEUE = "NotifyQuizReady";

export interface NotifyQuizReadyPayload {
  user_id: string;
  quiz_id: string;
  message: string;
}

export const notifyQuizReadyQueue = new Queue<NotifyQuizReadyPayload>(NOTIFY_QUIZ_READY_QUEUE, {
  connection,
});

export async function enqueueNotifyQuizReady(payload: NotifyQuizReadyPayload) {
  return notifyQuizReadyQueue.add(NOTIFY_QUIZ_READY_QUEUE, payload, {
    attempts: 3,
    backoff: { type: "exponential", delay: 1000 },
  });
}
```

- [ ] **Step 2: Write the failing test**

Create `services/notifications/test/notifyQuizReady.test.ts`:

```typescript
import { test } from "node:test";
import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import { prisma } from "../src/db";
import { processNotifyQuizReady } from "../src/jobs/notifyQuizReady";

const ALICE_ID = "11111111-1111-1111-1111-111111111111";

test("processNotifyQuizReady writes a notification row", async () => {
  const quizId = randomUUID();
  const fakeJob = {
    data: { user_id: ALICE_ID, quiz_id: quizId, message: "Your quiz is ready!" },
  } as any;

  await processNotifyQuizReady(fakeJob);

  const rows = await prisma.notification.findMany({ where: { quiz_id: quizId } });
  assert.equal(rows.length, 1);
  assert.equal(rows[0].user_id, ALICE_ID);
  assert.equal(rows[0].message, "Your quiz is ready!");
  assert.equal(rows[0].read, false);
});
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd services/notifications
npm run build
```

Expected: FAIL — `tsc` error, `src/jobs/notifyQuizReady.ts` doesn't exist (`Cannot find module '../src/jobs/notifyQuizReady'`).

- [ ] **Step 4: Write the implementation**

Create `services/notifications/src/jobs/notifyQuizReady.ts`:

```typescript
import { Worker, Job } from "bullmq";
import { connection, NOTIFY_QUIZ_READY_QUEUE, NotifyQuizReadyPayload } from "../queue";
import { prisma } from "../db";
import { logger } from "../logger";

export async function processNotifyQuizReady(job: Job<NotifyQuizReadyPayload>) {
  const { user_id, quiz_id, message } = job.data;
  await prisma.notification.create({
    data: { user_id, quiz_id, message },
  });
}

export function startNotifyQuizReadyWorker() {
  const worker = new Worker<NotifyQuizReadyPayload>(NOTIFY_QUIZ_READY_QUEUE, processNotifyQuizReady, {
    connection,
  });
  worker.on("failed", (job, err) => {
    logger.error({ jobId: job?.id, err }, "notify_quiz_ready_job_failed");
  });
  return worker;
}
```

- [ ] **Step 5: Run test to verify it passes**

Requires `postgres` and `redis` running (`docker-compose up -d postgres redis` from repo root).

```bash
cd services/notifications
export DATABASE_URL="postgresql://edumind:edumind@localhost:5432/edumind"
export REDIS_URL="redis://localhost:6379/1"
npm test
```

Expected: `notifyQuizReady.test.ts`'s test passes (plus the 4 from Task 4, still green).

- [ ] **Step 6: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/notifications/src/queue.ts services/notifications/src/jobs/notifyQuizReady.ts services/notifications/test/notifyQuizReady.test.ts
git commit -m "feat(notifications): add BullMQ queue and NotifyQuizReady job processor"
```

---

### Task 6: Fastify routes + main.ts wiring (with tests)

**Files:**
- Create: `services/notifications/src/routes.ts`
- Create: `services/notifications/src/main.ts`
- Create: `services/notifications/test/routes.test.ts`

**Interfaces:**
- Consumes: `requireUser` (Task 4), `enqueueNotifyQuizReady` (Task 5), `prisma` (Task 4), `logger` (Task 2).
- Produces: `buildApp(): FastifyInstance` (`src/main.ts`) — consumed by this task's own tests and available for future use; the `POST /notifications` and `GET /notifications` HTTP endpoints.

- [ ] **Step 1: Write the failing tests**

Create `services/notifications/test/routes.test.ts`:

```typescript
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildApp } from "../src/main";

const ALICE_ID = "11111111-1111-1111-1111-111111111111";
const BOB_ID = "22222222-2222-2222-2222-222222222222";
const UNKNOWN_ID = "99999999-9999-9999-9999-999999999999";

function auth(userId: string) {
  return { "x-user-id": userId };
}

test("POST /notifications enqueues a job and returns 202", async () => {
  const app = buildApp();
  const response = await app.inject({
    method: "POST",
    url: "/notifications",
    headers: auth(ALICE_ID),
    payload: {
      user_id: ALICE_ID,
      quiz_id: "33333333-3333-3333-3333-333333333333",
      message: "Your quiz is ready!",
    },
  });
  assert.equal(response.statusCode, 202);
  await app.close();
});

test("GET /notifications returns the caller's own notifications", async () => {
  const app = buildApp();
  const response = await app.inject({
    method: "GET",
    url: `/notifications?user_id=${ALICE_ID}`,
    headers: auth(ALICE_ID),
  });
  assert.equal(response.statusCode, 200);
  assert.ok(Array.isArray(response.json()));
  await app.close();
});

test("GET /notifications returns 401 with missing X-User-Id", async () => {
  const app = buildApp();
  const response = await app.inject({
    method: "GET",
    url: `/notifications?user_id=${ALICE_ID}`,
  });
  assert.equal(response.statusCode, 401);
  await app.close();
});

test("GET /notifications returns 401 with an unknown X-User-Id", async () => {
  const app = buildApp();
  const response = await app.inject({
    method: "GET",
    url: `/notifications?user_id=${ALICE_ID}`,
    headers: auth(UNKNOWN_ID),
  });
  assert.equal(response.statusCode, 401);
  await app.close();
});

test("GET /notifications returns 404 when user_id doesn't match the caller", async () => {
  const app = buildApp();
  const response = await app.inject({
    method: "GET",
    url: `/notifications?user_id=${ALICE_ID}`,
    headers: auth(BOB_ID),
  });
  assert.equal(response.statusCode, 404);
  await app.close();
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/notifications
npm run build
```

Expected: FAIL — `tsc` error, `src/main.ts` and `src/routes.ts` don't exist yet.

- [ ] **Step 3: Write routes.ts**

Create `services/notifications/src/routes.ts`:

```typescript
import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { requireUser } from "./identity";
import { prisma } from "./db";
import { enqueueNotifyQuizReady } from "./queue";

const createNotificationSchema = z.object({
  user_id: z.string().uuid(),
  quiz_id: z.string().uuid(),
  message: z.string().min(1),
});

const listQuerySchema = z.object({
  user_id: z.string().uuid(),
});

export async function registerRoutes(app: FastifyInstance) {
  app.addHook("preHandler", requireUser);

  app.post("/notifications", async (request, reply) => {
    const body = createNotificationSchema.parse(request.body);
    await enqueueNotifyQuizReady(body);
    return reply.code(202).send({ enqueued: true });
  });

  app.get("/notifications", async (request, reply) => {
    const query = listQuerySchema.parse(request.query);
    if (query.user_id !== request.user!.id) {
      return reply.code(404).send({ error: "Not found" });
    }
    const notifications = await prisma.notification.findMany({
      where: { user_id: query.user_id },
      orderBy: { created_at: "desc" },
    });
    return notifications;
  });
}
```

- [ ] **Step 4: Write main.ts**

Create `services/notifications/src/main.ts`:

```typescript
import Fastify from "fastify";
import { ZodError } from "zod";
import { registerRoutes } from "./routes";
import { startNotifyQuizReadyWorker } from "./jobs/notifyQuizReady";
import { logger } from "./logger";

export function buildApp() {
  const app = Fastify({ logger: true });

  app.setErrorHandler((error, _request, reply) => {
    if (error instanceof ZodError) {
      return reply.code(400).send({ error: "Invalid request", details: error.issues });
    }
    logger.error(error);
    return reply.code(500).send({ error: "Internal server error" });
  });

  app.register(registerRoutes);

  return app;
}

async function main() {
  const app = buildApp();
  const httpPort = Number(process.env.HTTP_PORT ?? 5000);
  await app.listen({ port: httpPort, host: "0.0.0.0" });

  startNotifyQuizReadyWorker();
  logger.info("BullMQ worker started");
}

if (require.main === module) {
  main().catch((err) => {
    logger.error(err);
    process.exit(1);
  });
}
```

- [ ] **Step 5: Run tests to verify they pass**

Requires `postgres` and `redis` running.

```bash
cd services/notifications
export DATABASE_URL="postgresql://edumind:edumind@localhost:5432/edumind"
export REDIS_URL="redis://localhost:6379/1"
npm test
```

Expected: all tests across `identity.test.ts`, `notifyQuizReady.test.ts`, and `routes.test.ts` pass (10 total).

- [ ] **Step 6: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/notifications/src/routes.ts services/notifications/src/main.ts services/notifications/test/routes.test.ts
git commit -m "feat(notifications): add POST/GET /notifications endpoints"
```

---

### Task 7: gRPC server (with test)

**Files:**
- Create: `services/notifications/src/grpc/server.ts`
- Modify: `services/notifications/src/main.ts` (start the gRPC server too)
- Create: `services/notifications/test/grpc.test.ts`

**Interfaces:**
- Consumes: `enqueueNotifyQuizReady` (Task 5), `logger` (Task 2), `proto/notifications.proto` (Task 1, copied locally via `npm run copy-proto`).
- Produces: `startGrpcServer(port: number): grpc.Server` (`src/grpc/server.ts`) — consumed by `main.ts` and Task 9's Python client (which calls the running server, not this function directly).

- [ ] **Step 1: Write the failing test**

Create `services/notifications/test/grpc.test.ts`:

```typescript
import { test } from "node:test";
import assert from "node:assert/strict";
import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { startGrpcServer } from "../src/grpc/server";
import { prisma } from "../src/db";
import { startNotifyQuizReadyWorker } from "../src/jobs/notifyQuizReady";

const ALICE_ID = "11111111-1111-1111-1111-111111111111";
const TEST_GRPC_PORT = 5099;

function loadClient() {
  const PROTO_PATH = path.join(__dirname, "..", "proto", "notifications.proto");
  const packageDefinition = protoLoader.loadSync(PROTO_PATH, { keepCase: true });
  const proto = grpc.loadPackageDefinition(packageDefinition) as any;
  return new proto.notifications.NotificationService(
    `localhost:${TEST_GRPC_PORT}`,
    grpc.credentials.createInsecure()
  );
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

test("NotifyQuizReady enqueues a job that eventually writes a notification row", async () => {
  const server = startGrpcServer(TEST_GRPC_PORT);
  const worker = startNotifyQuizReadyWorker();
  const client = loadClient();
  const quizId = randomUUID();

  const response = await new Promise<any>((resolve, reject) => {
    client.NotifyQuizReady({ user_id: ALICE_ID, quiz_id: quizId }, (err: any, res: any) => {
      if (err) reject(err);
      else resolve(res);
    });
  });
  assert.equal(response.accepted, true);

  let rows: any[] = [];
  for (let i = 0; i < 20; i++) {
    rows = await prisma.notification.findMany({ where: { quiz_id: quizId } });
    if (rows.length > 0) break;
    await sleep(200);
  }
  assert.equal(rows.length, 1);
  assert.equal(rows[0].user_id, ALICE_ID);

  await worker.close();
  await new Promise<void>((resolve) => server.tryShutdown(() => resolve()));
});
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd services/notifications
npm run build
```

Expected: FAIL — `tsc` error, `src/grpc/server.ts` doesn't exist yet.

- [ ] **Step 3: Write the gRPC server**

Create `services/notifications/src/grpc/server.ts`:

```typescript
import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";
import path from "node:path";
import { enqueueNotifyQuizReady } from "../queue";
import { logger } from "../logger";

const PROTO_PATH = path.join(__dirname, "..", "..", "proto", "notifications.proto");

const packageDefinition = protoLoader.loadSync(PROTO_PATH, {
  keepCase: true,
  longs: String,
  enums: String,
  defaults: true,
  oneofs: true,
});

const proto = grpc.loadPackageDefinition(packageDefinition) as any;

interface NotifyQuizReadyRequest {
  user_id: string;
  quiz_id: string;
}

interface NotifyQuizReadyResponse {
  accepted: boolean;
}

async function notifyQuizReady(
  call: grpc.ServerUnaryCall<NotifyQuizReadyRequest, NotifyQuizReadyResponse>,
  callback: grpc.sendUnaryData<NotifyQuizReadyResponse>
) {
  const { user_id, quiz_id } = call.request;
  try {
    await enqueueNotifyQuizReady({
      user_id,
      quiz_id,
      message: "Your quiz is ready!",
    });
    callback(null, { accepted: true });
  } catch (err) {
    logger.error(err, "notify_quiz_ready_grpc_failed");
    callback({ code: grpc.status.INTERNAL, message: "Failed to enqueue notification" });
  }
}

export function startGrpcServer(port: number) {
  const server = new grpc.Server();
  server.addService(proto.notifications.NotificationService.service, {
    NotifyQuizReady: notifyQuizReady,
  });
  server.bindAsync(`0.0.0.0:${port}`, grpc.ServerCredentials.createInsecure(), (err) => {
    if (err) {
      logger.error(err, "grpc_bind_failed");
      throw err;
    }
  });
  return server;
}
```

- [ ] **Step 4: Wire the gRPC server into main.ts**

Modify `services/notifications/src/main.ts` — add the import and startup call:

```typescript
import Fastify from "fastify";
import { ZodError } from "zod";
import { registerRoutes } from "./routes";
import { startNotifyQuizReadyWorker } from "./jobs/notifyQuizReady";
import { startGrpcServer } from "./grpc/server";
import { logger } from "./logger";

export function buildApp() {
  const app = Fastify({ logger: true });

  app.setErrorHandler((error, _request, reply) => {
    if (error instanceof ZodError) {
      return reply.code(400).send({ error: "Invalid request", details: error.issues });
    }
    logger.error(error);
    return reply.code(500).send({ error: "Internal server error" });
  });

  app.register(registerRoutes);

  return app;
}

async function main() {
  const app = buildApp();
  const httpPort = Number(process.env.HTTP_PORT ?? 5000);
  await app.listen({ port: httpPort, host: "0.0.0.0" });

  startNotifyQuizReadyWorker();
  logger.info("BullMQ worker started");

  const grpcPort = Number(process.env.GRPC_PORT ?? 5001);
  startGrpcServer(grpcPort);
  logger.info(`gRPC server listening on port ${grpcPort}`);
}

if (require.main === module) {
  main().catch((err) => {
    logger.error(err);
    process.exit(1);
  });
}
```

- [ ] **Step 5: Run test to verify it passes**

Requires `postgres` and `redis` running.

```bash
cd services/notifications
export DATABASE_URL="postgresql://edumind:edumind@localhost:5432/edumind"
export REDIS_URL="redis://localhost:6379/1"
npm test
```

Expected: all tests pass (11 total across the 4 test files).

- [ ] **Step 6: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/notifications/src/grpc/server.ts services/notifications/src/main.ts services/notifications/test/grpc.test.ts
git commit -m "feat(notifications): add gRPC NotifyQuizReady server"
```

---

### Task 8: Dockerfile for notifications

**Files:**
- Create: `services/notifications/Dockerfile`
- Create: `services/notifications/.dockerignore`

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: a buildable image with `CMD` that runs `prisma migrate deploy` then starts `dist/src/main.js` — consumed by Task 11 (docker-compose).

- [ ] **Step 1: Write .dockerignore**

Create `services/notifications/.dockerignore`:

```
node_modules
dist
proto
.env
```

- [ ] **Step 2: Write the Dockerfile**

Create `services/notifications/Dockerfile` (build context will be the repo root — see Task 11 — so all paths here are root-relative):

```dockerfile
FROM node:20-slim AS build
WORKDIR /app

COPY services/notifications/package.json services/notifications/package-lock.json* ./
RUN npm install

COPY services/notifications/ .
COPY proto/notifications.proto ./proto/notifications.proto

RUN npx prisma generate
RUN npx tsc

FROM node:20-slim
WORKDIR /app

COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
COPY --from=build /app/proto ./proto
COPY --from=build /app/prisma ./prisma
COPY --from=build /app/package.json ./package.json

CMD ["sh", "-c", "npx prisma migrate deploy && node dist/src/main.js"]
```

- [ ] **Step 3: Verify it builds (standalone, before compose wiring)**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
docker build -f services/notifications/Dockerfile -t notifications-test .
```

Expected: build succeeds (this only proves the image builds — it isn't run yet; running it is covered by Task 11's `docker-compose up`).

- [ ] **Step 4: Commit**

```bash
git add services/notifications/Dockerfile services/notifications/.dockerignore
git commit -m "feat(notifications): add Dockerfile"
```

---

### Task 9: core-api gRPC client

**Files:**
- Create: `services/core-api/grpc_client.py`

**Interfaces:**
- Consumes: `notifications_pb2`, `notifications_pb2_grpc` (generated by Task 1's `make proto`).
- Produces: `notify_quiz_ready(user_id: str, quiz_id: str) -> None` (raises `grpc.RpcError` on failure — caller's responsibility to catch) — consumed by Task 10.

- [ ] **Step 1: Regenerate stubs locally if needed**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
ls services/core-api/notifications_pb2.py 2>/dev/null || make proto
```

- [ ] **Step 2: Write the client**

Create `services/core-api/grpc_client.py`:

```python
import os
import grpc
import notifications_pb2
import notifications_pb2_grpc

NOTIFICATIONS_GRPC_URL = os.getenv("NOTIFICATIONS_GRPC_URL", "localhost:5001")


def notify_quiz_ready(user_id: str, quiz_id: str) -> None:
    with grpc.insecure_channel(NOTIFICATIONS_GRPC_URL) as channel:
        stub = notifications_pb2_grpc.NotificationServiceStub(channel)
        stub.NotifyQuizReady(
            notifications_pb2.NotifyQuizReadyRequest(user_id=user_id, quiz_id=quiz_id),
            timeout=5,
        )
```

- [ ] **Step 3: Verify it imports and fails cleanly with nothing listening**

```bash
cd services/core-api
python3 -c "
import sys
sys.path.insert(0, '.')
import grpc
from grpc_client import notify_quiz_ready
try:
    notify_quiz_ready('11111111-1111-1111-1111-111111111111', '22222222-2222-2222-2222-222222222222')
    print('UNEXPECTED: call succeeded with nothing listening')
except grpc.RpcError as e:
    print('OK: got expected RpcError:', e.code())
"
```

Expected: prints `OK: got expected RpcError: StatusCode.UNAVAILABLE` (nothing is listening on port 5001 in this standalone check).

- [ ] **Step 4: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/core-api/grpc_client.py
git commit -m "feat(core-api): add gRPC client for the notifications service"
```

---

### Task 10: Wire the gRPC call into create_quiz

**Files:**
- Modify: `services/core-api/routes.py`

**Interfaces:**
- Consumes: `notify_quiz_ready` (Task 9), `log` (existing, `services/core-api/logger.py`).

- [ ] **Step 1: Write the failing tests**

Add `import grpc` to the top of `services/core-api/tests/test_routes.py`'s import
block, then add these two tests (after `test_quiz_crud_happy_path`):

```python
@pytest.mark.asyncio
async def test_create_quiz_calls_notify_quiz_ready(monkeypatch):
    called = {}

    def fake_notify_quiz_ready(user_id, quiz_id):
        called["user_id"] = user_id
        called["quiz_id"] = quiz_id

    monkeypatch.setattr("routes.notify_quiz_ready", fake_notify_quiz_ready)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Notify notes")
        quiz = await create_quiz(client, ALICE_ID, document["id"], "Notify quiz")

    assert called["user_id"] == ALICE_ID
    assert called["quiz_id"] == quiz["id"]


@pytest.mark.asyncio
async def test_create_quiz_succeeds_even_when_notify_quiz_ready_raises(monkeypatch):
    def failing_notify_quiz_ready(user_id, quiz_id):
        raise grpc.RpcError("simulated failure")

    monkeypatch.setattr("routes.notify_quiz_ready", failing_notify_quiz_ready)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        document = await create_document(client, ALICE_ID, "Resilience notes")
        quiz = await create_quiz(client, ALICE_ID, document["id"], "Resilience quiz")

    assert quiz["topic"] == "Resilience quiz"
```

The first test proves the integration point actually exists (a test that
only checks quiz creation still succeeds would pass identically whether or
not `create_quiz` calls `notify_quiz_ready` at all — not a real test of the
wiring). The second proves the best-effort/never-fails-the-request
behavior specifically, by forcing the failure rather than relying on
nothing listening on port 5001 in the test environment.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/core-api
source /tmp/edumind_venv/bin/activate 2>/dev/null || (python3 -m venv /tmp/edumind_venv && source /tmp/edumind_venv/bin/activate && pip install -q -r requirements.txt)
python -m pytest tests/test_routes.py::test_create_quiz_calls_notify_quiz_ready tests/test_routes.py::test_create_quiz_succeeds_even_when_notify_quiz_ready_raises -v
```

Expected: FAIL — `monkeypatch.setattr("routes.notify_quiz_ready", ...)` raises `AttributeError: <module 'routes'> does not have the attribute 'notify_quiz_ready'`, since `routes.py` doesn't import it yet.

- [ ] **Step 3: Modify create_quiz**

Modify `services/core-api/routes.py` — add the import at the top:

```python
from database import get_db
from identity import get_current_user
from models import User, Document, Quiz, QuizAttempt
from logger import log
import grpc
from grpc_client import notify_quiz_ready
```

Then modify the `create_quiz` function:

```python
@router.post("/quizzes")
async def create_quiz(
    request: QuizCreateRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await _get_owned_document(request.document_id, user, db)
    quiz = Quiz(document_id=request.document_id, topic=request.topic, questions=request.questions)
    db.add(quiz)
    await db.commit()
    await db.refresh(quiz)
    try:
        notify_quiz_ready(str(user.id), str(quiz.id))
    except grpc.RpcError as e:
        log.warning("notify_quiz_ready_failed", quiz_id=str(quiz.id), error=str(e))
    return quiz
```

- [ ] **Step 4: Run the new tests and the full suite to verify they pass**

```bash
cd services/core-api
python -m pytest tests/ -v
```

Expected: all 13 tests pass (the 11 from before plus the two new gRPC-integration tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
git add services/core-api/routes.py services/core-api/tests/test_routes.py
git commit -m "feat(core-api): call notifications gRPC service after quiz creation"
```

---

### Task 11: docker-compose wiring (repo-root build contexts)

**Files:**
- Modify: `services/core-api/Dockerfile`
- Modify: `docker-compose.yml`

**Interfaces:**
- Consumes: everything from Tasks 1–10.

- [ ] **Step 1: Update core-api's Dockerfile for a repo-root build context**

Modify `services/core-api/Dockerfile` — replace entire contents:

```dockerfile
FROM python:3.13-slim

WORKDIR /app

COPY services/core-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto/notifications.proto ./proto/notifications.proto
RUN python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/notifications.proto

COPY services/core-api/ .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 2: Update docker-compose.yml**

Modify `docker-compose.yml` — replace entire contents:

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
```

- [ ] **Step 3: Verify core-api and worker still build with the new context**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
docker build -f services/core-api/Dockerfile -t core-api-test .
```

Expected: build succeeds (proto codegen step included).

- [ ] **Step 4: Commit**

```bash
git add services/core-api/Dockerfile docker-compose.yml
git commit -m "feat: wire notifications service into docker-compose, move core-api to repo-root build context"
```

---

### Task 12: Full-stack verification

**Files:** none (verification only).

- [ ] **Step 1: Bring up the full stack**

```bash
cd /Users/shivam/Desktop/projects_2/python_backend_refresher
docker-compose down -v
docker-compose up --build -d
```

Expected: all six services (`postgres`, `redis`, `core-api`, `worker`, `notifications`, `prometheus`, `grafana`) start; `docker-compose ps` shows `postgres` healthy and `core-api`/`notifications` running (not restarting).

If port `8000` is already held by an unrelated container on the host (as happened during the earlier EduMind phase verification), skip straight to Step 2 and run `pytest`/`node --test` against the already-running `postgres`/`redis` containers instead of through the mapped HTTP ports.

- [ ] **Step 2: Verify notifications' migration applied inside the container**

```bash
docker exec python_backend_refresher-postgres-1 psql -U edumind -d edumind -c "\d notifications"
```

Expected: same output as Task 3 Step 7.

- [ ] **Step 3: Run core-api's test suite**

```bash
cd services/core-api
source /tmp/edumind_venv/bin/activate 2>/dev/null || (python3 -m venv /tmp/edumind_venv && source /tmp/edumind_venv/bin/activate && pip install -q -r requirements.txt)
python -m pytest tests/ -v
```

Expected: all 13 tests pass.

- [ ] **Step 4: Run notifications' test suite**

```bash
cd services/notifications
export DATABASE_URL="postgresql://edumind:edumind@localhost:5432/edumind"
export REDIS_URL="redis://localhost:6379/1"
npm test
```

Expected: all 11 tests pass.

- [ ] **Step 5: Manual end-to-end check — quiz creation triggers a real notification**

```bash
ALICE_ID="11111111-1111-1111-1111-111111111111"
BOB_ID="22222222-2222-2222-2222-222222222222"

DOC_ID=$(curl -s -X POST http://localhost:8000/documents \
  -H "X-User-Id: $ALICE_ID" -H "Content-Type: application/json" \
  -d '{"title": "E2E notes", "status": "uploaded"}' | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

QUIZ_ID=$(curl -s -X POST http://localhost:8000/quizzes \
  -H "X-User-Id: $ALICE_ID" -H "Content-Type: application/json" \
  -d "{\"document_id\": \"$DOC_ID\", \"topic\": \"E2E quiz\", \"questions\": []}" | python3 -c "import sys, json; print(json.load(sys.stdin)['id'])")

sleep 2

echo "Alice's notifications (expect 1 row for quiz $QUIZ_ID):"
curl -s "http://localhost:5000/notifications?user_id=$ALICE_ID" -H "X-User-Id: $ALICE_ID"

echo "Bob trying Alice's notifications (expect 404):"
curl -s -o /dev/null -w "%{http_code}\n" "http://localhost:5000/notifications?user_id=$ALICE_ID" -H "X-User-Id: $BOB_ID"
```

Expected: the notifications list includes one row with `"quiz_id": "<QUIZ_ID>"` and `"message": "Your quiz is ready!"`; Bob's request prints `404`.

- [ ] **Step 6: Tear down or leave running**

```bash
docker-compose down
```

(Leave running instead if you want to keep exploring manually — this step is a judgment call, not a hard requirement.)

No commit for this task — verification only.
