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
