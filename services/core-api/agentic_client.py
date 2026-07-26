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
