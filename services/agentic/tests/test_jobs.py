import core.jobs


def test_run_agent_job_posts_result_to_callback(monkeypatch):
    fake_result = {"answer": "Paris is the capital of France.", "intent": "answer"}
    monkeypatch.setattr("core.jobs.agent.invoke", lambda state, config: fake_result)

    posted = {}

    class FakeResponse:
        def raise_for_status(self):
            pass

    def fake_post(url, json, timeout):
        posted["url"] = url
        posted["json"] = json
        return FakeResponse()

    monkeypatch.setattr("core.jobs.httpx.post", fake_post)

    core.jobs.run_agent_job(
        question="What is the capital of France?",
        document_id="11111111-1111-1111-1111-111111111111",
        chat_id="22222222-2222-2222-2222-222222222222",
        message_id="33333333-3333-3333-3333-333333333333",
    )

    assert posted["url"] == "http://localhost:8000/internal/chat-answers"
    assert posted["json"]["chat_id"] == "22222222-2222-2222-2222-222222222222"
    assert posted["json"]["message_id"] == "33333333-3333-3333-3333-333333333333"
    assert posted["json"]["result"]["answer"] == "Paris is the capital of France."
    assert "thread_id" in posted["json"]["result"]


def test_run_agent_job_swallows_callback_failure(monkeypatch, capsys):
    monkeypatch.setattr("core.jobs.agent.invoke", lambda state, config: {"answer": "x"})

    def failing_post(url, json, timeout):
        raise ConnectionError("core-api unreachable")

    monkeypatch.setattr("core.jobs.httpx.post", failing_post)

    core.jobs.run_agent_job(
        question="q", document_id="d", chat_id="c", message_id="m"
    )  # must not raise

    captured = capsys.readouterr()
    assert "chat_answer_callback_failed" in captured.out
