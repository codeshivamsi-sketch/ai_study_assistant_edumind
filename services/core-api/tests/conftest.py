import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

RETRY_TEST_QUEUE = "notify_quiz_ready_retry_test"
CORE_API_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def retry_test_worker():
    """Spawns a dedicated Celery worker for test_worker_retry.py.

    That test needs a worker consuming its own queue with a fast retry
    countdown, distinct from the main `worker` service (celery queue,
    60s countdown) - no such worker exists otherwise. NOTIFICATIONS_GRPC_URL
    points at a guaranteed-closed port so the retry-then-fail path is
    deterministic, not dependent on the real notifications service being
    down (which is what made this test pass by accident previously).
    """
    env = {
        **os.environ,
        "NOTIFY_QUIZ_READY_RETRY_COUNTDOWN": "1",
        "NOTIFICATIONS_GRPC_URL": "localhost:1",
    }
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "celery", "-A", "worker", "worker",
            "-Q", RETRY_TEST_QUEUE, "--concurrency=1", "--loglevel=info",
        ],
        cwd=CORE_API_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        from worker import celery_app

        inspector = celery_app.control.inspect(timeout=1)
        deadline = time.monotonic() + 15
        ready = False
        while time.monotonic() < deadline:
            queues = inspector.active_queues() or {}
            if any(
                q["name"] == RETRY_TEST_QUEUE
                for worker_queues in queues.values()
                for q in worker_queues
            ):
                ready = True
                break
            time.sleep(0.3)
        if not ready:
            pytest.fail(f"{RETRY_TEST_QUEUE} worker did not start within 15s")
        yield
    finally:
        proc.terminate()
        proc.wait(timeout=5)
