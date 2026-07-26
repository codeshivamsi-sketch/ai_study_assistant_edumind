import os
import uuid
import httpx
from agents.agents import agent

CORE_API_CALLBACK_URL = os.getenv("CORE_API_CALLBACK_URL", "http://localhost:8000")


def run_agent_job(question: str, document_id: str, chat_id: str, message_id: str) -> None:
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"question": question, "document_id": document_id}, config=config)

    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "result": {**result, "thread_id": thread_id},
    }
    try:
        response = httpx.post(f"{CORE_API_CALLBACK_URL}/internal/chat-answers", json=payload, timeout=30)
        response.raise_for_status()
    except Exception as exc:
        print(f"chat_answer_callback_failed chat_id={chat_id} message_id={message_id} error={exc}")
