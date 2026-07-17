import * as grpc from "@grpc/grpc-js";
import * as protoLoader from "@grpc/proto-loader";
import path from "node:path";
import { enqueueNotifyQuizReady } from "../queue";
import { logger } from "../logger";

const PROTO_PATH = path.join(__dirname, "..", "..", "..", "proto", "notifications.proto");

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
