import os
import grpc
import notifications_pb2
import notifications_pb2_grpc

NOTIFICATIONS_GRPC_URL = os.getenv("NOTIFICATIONS_GRPC_URL", "localhost:5001")


def notify_quiz_ready(user_id: str, quiz_id: str) -> None:
    with grpc.insecure_channel(NOTIFICATIONS_GRPC_URL) as channel:
        stub = notifications_pb2_grpc.NotificationServiceStub(channel)
        stub.NotifyQuizReady(
            notifications_pb2.NotifyQuizReadyRequest(user_id=user_id, quiz_id=quiz_id),
            timeout=5,
        )
