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
