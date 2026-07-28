import Fastify from "fastify";
import cors from "@fastify/cors";
import { ZodError } from "zod";
import { registerRoutes } from "./routes";
import { startNotifyQuizReadyWorker } from "./jobs/notifyQuizReady";
import { startGrpcServer } from "./grpc/server";
import { logger } from "./logger";

const FRONTEND_ORIGINS = [
  "http://localhost:3001",
  "http://localhost:3005",
  "http://localhost:3105",
];

export function buildApp() {
  const app = Fastify({ logger: true });

  app.register(cors, { origin: FRONTEND_ORIGINS });

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
