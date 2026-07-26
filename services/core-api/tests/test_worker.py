from worker import notify_quiz_ready


def test_notify_quiz_ready_calls_grpc_client(monkeypatch):
    called = {}

    def fake_send(user_id, quiz_id=None, chat_id=None, message_id=None):
        called["user_id"] = user_id
        called["quiz_id"] = quiz_id

    monkeypatch.setattr("worker.send_grpc_notification", fake_send)

    result = notify_quiz_ready.apply(args=["u1", "q1"])

    assert result.successful()
    assert called == {"user_id": "u1", "quiz_id": "q1"}
