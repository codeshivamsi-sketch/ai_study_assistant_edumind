import asyncio
import requests
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

BASE_URL = "http://localhost:8000"

app = Server("edumind")

@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="query_curriculum",
            description="Answer a question using the uploaded curriculum. Returns a grounded answer with source references.",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {"type": "string", "description": "The question to ask"}
                },
                "required": ["question"]
            }
        ),
        types.Tool(
            name="get_related_concepts",
            description="Get concepts related to a topic from the knowledge graph.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "The topic to find related concepts for"}
                },
                "required": ["topic"]
            }
        ),
        types.Tool(
            name="generate_quiz",
            description="Generate quiz questions on a topic from the curriculum.",
            inputSchema={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Topic to quiz on"},
                    "num_questions": {"type": "integer", "description": "Number of questions", "default": 3}
                },
                "required": ["topic"]
            }
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "query_curriculum":
        response = requests.post(f"{BASE_URL}/query", json={"question": arguments["question"]})
        result = response.json()
        return [types.TextContent(type="text", text=result["answer"])]

    elif name == "get_related_concepts":
        response = requests.post(f"{BASE_URL}/query", json={"question": f"what is related to {arguments['topic']}"})
        result = response.json()
        concepts = result.get("related_concepts", [])
        return [types.TextContent(type="text", text=f"Related concepts: {', '.join(concepts) if concepts else 'None found'}")]

    elif name == "generate_quiz":
        topic = arguments["topic"]
        num = arguments.get("num_questions", 3)
        response = requests.post(f"{BASE_URL}/agent", json={"question": f"quiz me on {topic} with {num} questions"})
        result = response.json()
        quiz = result.get("quiz_questions", ["No quiz generated"])
        return [types.TextContent(type="text", text="\n".join(quiz))]

    return [types.TextContent(type="text", text="Unkown tool")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())