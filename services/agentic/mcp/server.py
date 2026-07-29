import os
import requests
from mcp.server import MCPServer

# EDUMIND_BASE_URL: inside docker-compose this is set to "http://agentic:8000"
# (internal network, internal port). Falls back to the host-mapped port for
# anyone running this locally via stdio instead of the mcp-server container.
BASE_URL = os.getenv("EDUMIND_BASE_URL", "http://localhost:8002")

mcp = MCPServer("edumind")


def _call_agent(question: str) -> dict:
    response = requests.post(f"{BASE_URL}/agent/sync", json={"question": question})
    response.raise_for_status()
    return response.json()


@mcp.tool()
def query_curriculum(question: str) -> str:
    """Answer a question using the uploaded curriculum. Routes through the
    same LangGraph agent used by chat (/agent/sync), which classifies intent
    and retrieves context before answering."""
    result = _call_agent(question)
    return result.get("answer", "No answer generated")


@mcp.tool()
def get_related_concepts(topic: str) -> str:
    """Get concepts related to a topic from the knowledge graph. Routes
    through /agent/sync - every intent path runs retrieval first, which
    always populates related concepts regardless of what's asked."""
    result = _call_agent(f"what is related to {topic}")
    concepts = result.get("related_concepts", [])
    return f"Related concepts: {', '.join(concepts) if concepts else 'None found'}"


@mcp.tool()
def generate_quiz(topic: str, num_questions: int = 3) -> str:
    """Generate quiz questions on a topic. Routes through /agent/sync, which
    classifies 'quiz me on X' as quiz intent."""
    result = _call_agent(f"quiz me on {topic} with {num_questions} questions")
    quiz = result.get("quiz_questions", ["No quiz generated"])
    return "\n".join(quiz)


if __name__ == "__main__":
    mcp.run(
        transport=os.getenv("MCP_TRANSPORT", "stdio"),
        host="0.0.0.0",
        port=int(os.getenv("MCP_PORT", "8000")),
    )
