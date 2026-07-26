import os
import httpx

AGENTIC_SERVICE_URL = os.getenv("AGENTIC_SERVICE_URL", "http://localhost:8002")


async def upload_document(document_id: str, filename: str, content: bytes) -> None:
    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{AGENTIC_SERVICE_URL}/upload",
            files={"file": (filename, content, "application/pdf")},
            data={"document_id": document_id},
        )
        response.raise_for_status()


# ponytail: request_quiz kept here (not deleted per the brief's literal Step 1)
# because worker.py's already-merged `generate_quiz` Celery task still calls
# it and test_worker_generate_quiz.py still exercises that task; the brief's
# own rationale for deleting it is "its only caller is removed in Task 5" --
# deleting it now, before Task 5 removes that caller, would break the entire
# suite's import chain (main -> routes -> worker -> agentic_client), not just
# the message tests the brief anticipated. Delete alongside Task 5's removal
# of generate_quiz/request_quiz's caller.
def request_quiz(document_id: str, topic: str) -> list:
    response = httpx.post(
        f"{AGENTIC_SERVICE_URL}/agent",
        json={"question": f"Quiz me on {topic}", "document_id": document_id},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["quiz_questions"]


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
