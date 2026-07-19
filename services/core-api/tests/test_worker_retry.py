import time
from celery.result import AsyncResult
from worker import celery_app

ALICE_ID = "11111111-1111-1111-1111-111111111111"


def test_notify_quiz_ready_retries_then_fails():
    task = celery_app.send_task(
        "notify_quiz_ready",
        args=[ALICE_ID, "22222222-2222-2222-2222-222222222222"],
        queue="notify_quiz_ready_retry_test",
    )
    result = AsyncResult(task.id, app=celery_app)

    start = time.monotonic()
    timeout = 15
    while not result.ready() and time.monotonic() - start < timeout:
        time.sleep(0.2)
    elapsed = time.monotonic() - start

    assert result.ready(), f"task did not finish within {timeout}s (state={result.state})"
    assert result.state == "FAILURE"
    # 3 retries at ~1s each (NOTIFY_QUIZ_READY_RETRY_COUNTDOWN=1 in this
    # test's worker env) — proves the retry loop actually ran more than
    # once, not that it failed immediately on the first attempt.
    assert elapsed >= 2, f"expected at least ~3s of retries, only took {elapsed:.1f}s"
