import time
from celery.result import AsyncResult
from worker import celery_app

ALICE_ID = "11111111-1111-1111-1111-111111111111"
FAKE_DOCUMENT_ID = "33333333-3333-3333-3333-333333333333"


def test_generate_quiz_retries_then_fails():
    task = celery_app.send_task(
        "generate_quiz",
        args=[ALICE_ID, FAKE_DOCUMENT_ID, "Chapter 1"],
        queue="generate_quiz_retry_test",
    )
    result = AsyncResult(task.id, app=celery_app)

    start = time.monotonic()
    timeout = 15
    while not result.ready() and time.monotonic() - start < timeout:
        time.sleep(0.2)
    elapsed = time.monotonic() - start

    assert result.ready(), f"task did not finish within {timeout}s (state={result.state})"
    assert result.state == "FAILURE"
    # 2 retries at ~1s each (GENERATE_QUIZ_RETRY_COUNTDOWN=1 in this
    # test's worker env) -- proves the retry loop ran more than once,
    # not that it failed immediately on the first attempt.
    assert elapsed >= 1.5, f"expected at least ~2s of retries, only took {elapsed:.1f}s"
