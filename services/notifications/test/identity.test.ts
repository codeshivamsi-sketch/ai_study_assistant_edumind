import { test, after } from "node:test";
import assert from "node:assert/strict";
import Fastify from "fastify";
import { requireUser } from "../src/identity";
import { prisma } from "../src/db";

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

after(async () => {
  await prisma.$disconnect();
});
