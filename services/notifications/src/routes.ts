import type { FastifyInstance } from "fastify";
import { z } from "zod";
import { requireUser } from "./identity";
import { prisma } from "./db";
import { enqueueNotifyQuizReady } from "./queue";

const createNotificationSchema = z.object({
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
    await enqueueNotifyQuizReady({ ...body, user_id: request.user!.id });
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
