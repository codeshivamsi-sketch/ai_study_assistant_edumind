import os
import grpc
import notifications_pb2
import notifications_pb2_grpc

NOTIFICATIONS_GRPC_URL = os.getenv("NOTIFICATIONS_GRPC_URL", "localhost:5001")


def notify_quiz_ready(
    user_id: str,
    quiz_id: str | None = None,
    chat_id: str | None = None,
    message_id: str | None = None,
) -> None:
    request_kwargs = {"user_id": user_id}
    if quiz_id:
        request_kwargs["quiz_id"] = quiz_id
    if chat_id:
        request_kwargs["chat_id"] = chat_id
    if message_id:
        request_kwargs["message_id"] = message_id

    with grpc.insecure_channel(NOTIFICATIONS_GRPC_URL) as channel:
        stub = notifications_pb2_grpc.NotificationServiceStub(channel)
        stub.NotifyQuizReady(
            notifications_pb2.NotifyQuizReadyRequest(**request_kwargs),
            timeout=5,
        )
