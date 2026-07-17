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
