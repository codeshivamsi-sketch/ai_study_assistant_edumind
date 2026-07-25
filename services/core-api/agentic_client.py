import json
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


async def ask_question(document_id: str, question: str) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            f"{AGENTIC_SERVICE_URL}/agent",
            json={"question": question, "document_id": document_id},
        )
        response.raise_for_status()
        data = response.json()
    answer = data.get("answer")
    if answer is not None:
        return answer
    return json.dumps({k: v for k, v in data.items() if k not in ("question", "document_id")})


def request_quiz(document_id: str, topic: str) -> list:
    response = httpx.post(
        f"{AGENTIC_SERVICE_URL}/agent",
        json={"question": f"Quiz me on {topic}", "document_id": document_id},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["quiz_questions"]
