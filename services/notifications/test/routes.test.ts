import { test, after } from "node:test";
import assert from "node:assert/strict";
import { buildApp } from "../src/main";
import { prisma } from "../src/db";
import { connection, notifyQuizReadyQueue } from "../src/queue";

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

after(async () => {
  await notifyQuizReadyQueue.close();
  await connection.quit();
  await prisma.$disconnect();
});
