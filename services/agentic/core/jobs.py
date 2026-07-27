import os
import uuid
import httpx
from agents.agents import agent

CORE_API_CALLBACK_URL = os.getenv("CORE_API_CALLBACK_URL", "http://localhost:8000")
INTERNAL_CALLBACK_TOKEN = os.getenv("INTERNAL_CALLBACK_TOKEN", "dev-internal-token")


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
        response = httpx.post(
            f"{CORE_API_CALLBACK_URL}/internal/chat-answers",
            json=payload,
            headers={"X-Internal-Token": INTERNAL_CALLBACK_TOKEN},
            timeout=30,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"chat_answer_callback_failed chat_id={chat_id} message_id={message_id} error={exc}")
        raise


def run_evaluate_job(thread_id: str, user_answer: str, chat_id: str, message_id: str, quiz_id: str) -> None:
    config = {"configurable": {"thread_id": thread_id}}
    agent.update_state(config, {"user_answer": user_answer}, as_node="quiz")

    result = None
    for state in agent.stream(None, config=config):
        result = state
    evaluation = result.get("evaluate", {})

    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "result": {
            "intent": "quiz_answer",
            "quiz_id": quiz_id,
            "score": evaluation.get("score"),
            "feedback": evaluation.get("feedback"),
        },
    }
    try:
        response = httpx.post(
            f"{CORE_API_CALLBACK_URL}/internal/chat-answers",
            json=payload,
            headers={"X-Internal-Token": INTERNAL_CALLBACK_TOKEN},
            timeout=30,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"quiz_evaluation_callback_failed chat_id={chat_id} message_id={message_id} error={exc}")
        raise
