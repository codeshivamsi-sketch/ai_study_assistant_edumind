import os
import httpx

AGENTIC_SERVICE_URL = os.getenv("AGENTIC_SERVICE_URL", "http://localhost:8002")


async def upload_document(document_id: str, filename: str, content: bytes) -> None:
    # ponytail: flat timeout, not per-chunk-count budgeted. Ingestion calls
    # Claude once per chunk, sequentially — latency is dominated by that,
    # not file size. Raise further (or move ingestion off the request path
    # to the already-wired Celery worker, per CLAUDE.md's Decision) if this
    # still isn't enough headroom.
    async with httpx.AsyncClient(timeout=300) as client:
        response = await client.post(
            f"{AGENTIC_SERVICE_URL}/upload",
            files={"file": (filename, content, "application/pdf")},
            data={"document_id": document_id},
        )
        response.raise_for_status()


async def request_answer(chat_id: str, message_id: str, document_id: str, question: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{AGENTIC_SERVICE_URL}/agent",
            json={
                "question": question,
                "document_id": document_id,
                "chat_id": chat_id,
                "message_id": message_id,
            },
        )
        response.raise_for_status()


async def request_evaluation(
    thread_id: str, user_answer: str, chat_id: str, message_id: str, quiz_id: str
) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            f"{AGENTIC_SERVICE_URL}/evaluate",
            json={
                "thread_id": thread_id,
                "user_answer": user_answer,
                "chat_id": chat_id,
                "message_id": message_id,
                "quiz_id": quiz_id,
            },
        )
        response.raise_for_status()
