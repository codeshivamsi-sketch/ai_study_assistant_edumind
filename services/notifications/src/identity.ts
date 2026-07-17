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
