import os
from redis import Redis
from rq import Queue

AGENTIC_REDIS_URL = os.getenv("AGENTIC_REDIS_URL", "redis://localhost:6379/2")
redis_conn = Redis.from_url(AGENTIC_REDIS_URL)
job_queue = Queue("agent_jobs", connection=redis_conn)
