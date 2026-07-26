import notifications_pb2


def test_notify_quiz_ready_request_accepts_chat_fields_without_quiz_id():
    request = notifications_pb2.NotifyQuizReadyRequest(
        user_id="11111111-1111-1111-1111-111111111111",
        chat_id="22222222-2222-2222-2222-222222222222",
        message_id="33333333-3333-3333-3333-333333333333",
    )
    assert request.user_id == "11111111-1111-1111-1111-111111111111"
    assert request.chat_id == "22222222-2222-2222-2222-222222222222"
    assert request.message_id == "33333333-3333-3333-3333-333333333333"
    assert not request.HasField("quiz_id")


def test_notify_quiz_ready_request_still_accepts_quiz_id_only():
    request = notifications_pb2.NotifyQuizReadyRequest(
        user_id="11111111-1111-1111-1111-111111111111",
        quiz_id="44444444-4444-4444-4444-444444444444",
    )
    assert request.HasField("quiz_id")
    assert not request.HasField("chat_id")
