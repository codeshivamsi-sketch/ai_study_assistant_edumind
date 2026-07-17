import { test, after } from "node:test";
import assert from "node:assert/strict";
import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";
import path from "node:path";
import { randomUUID } from "node:crypto";
import { startGrpcServer } from "../src/grpc/server";
import { prisma } from "../src/db";
import { connection, notifyQuizReadyQueue } from "../src/queue";
import { startNotifyQuizReadyWorker } from "../src/jobs/notifyQuizReady";

const ALICE_ID = "11111111-1111-1111-1111-111111111111";
const TEST_GRPC_PORT = 5099;

function loadClient() {
  const PROTO_PATH = path.join(__dirname, "..", "..", "proto", "notifications.proto");
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

after(async () => {
  await notifyQuizReadyQueue.close();
  await connection.quit();
  await prisma.$disconnect();
});
