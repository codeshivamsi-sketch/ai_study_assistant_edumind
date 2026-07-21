# Study Assistant AI — EduMind

An AI-powered study assistant built with RAG, Knowledge Graphs, multi-agent orchestration, and RAGAs evaluation. Upload a PDF curriculum and ask questions, generate quizzes, get evaluated, or get summaries — all grounded in your content. Built to develop hands-on familiarity with agentic AI.

![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Claude](https://img.shields.io/badge/Claude-Anthropic-D97757?style=flat&logo=anthropic&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-LangChain-1C3C3C?style=flat&logo=langchain&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-Vector_DB-FF6B35?style=flat)
![Neo4j](https://img.shields.io/badge/Neo4j-Knowledge_Graph-008CC1?style=flat&logo=neo4j&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)
![LangSmith](https://img.shields.io/badge/LangSmith-Tracing-F5A623?style=flat)
![RAGAs](https://img.shields.io/badge/RAGAs-Evaluation-6C3483?style=flat)
![MCP](https://img.shields.io/badge/MCP-Model_Context_Protocol-000000?style=flat&logo=anthropic&logoColor=white)

---

## Architecture Overview

```mermaid
flowchart TD
    User([User]) -->|POST /upload| Upload[Upload Endpoint]
    User -->|POST /agent| Agent[Agent Endpoint]
    User -->|POST /evaluate| Evaluate[Evaluate Endpoint]

    subgraph Ingest Pipeline - Phase 1 & 2
        Upload --> Extract[pypdf - Extract Text]
        Extract --> Chunk[RecursiveCharacterTextSplitter\nchunk_size=500, overlap=50]
        Chunk --> Embed[SentenceTransformer\nall-MiniLM-L6-v2\n384 dimensions]
        Embed --> Chroma[(ChromaDB\nVector Store)]
        Chunk --> Claude1[Claude claude-opus-4-5\nEntity Extraction]
        Claude1 --> Neo4j[(Neo4j\nKnowledge Graph\nConcept Nodes + Relationships)]
    end

    subgraph Multi-Agent Graph - Phase 3
        Agent --> Orchestrator[Orchestrator Node\nClassify intent:\nanswer / quiz / summarize]
        Orchestrator --> Retrieval[Retrieval Node]
        Retrieval --> ChromaSearch[ChromaDB\nTop 3 similar chunks]
        Retrieval --> GraphSearch[Neo4j Traversal\nRelated concepts]
        ChromaSearch --> Route{Route by intent}
        GraphSearch --> Route
        Route -->|answer| AnswerNode[Answer Node\nClaude generates answer\nwith citations]
        Route -->|quiz| QuizNode[Quiz Node\nClaude generates\n3 quiz questions]
        Route -->|summarize| SummaryNode[Summarizer Node\nClaude generates\nstudy notes]
        QuizNode -->|INTERRUPT - wait for human| HITL([Human answers quiz])
        HITL -->|POST /evaluate| EvalNode[Evaluator Node\nClaude scores answer\nout of 10]
        AnswerNode --> END([Response])
        EvalNode --> END
        SummaryNode --> END
    end

    subgraph Infrastructure
        SQLite[(SQLite\nLangGraph Checkpoints\nHITL State)]
        LangSmith[LangSmith\nTracing & Observability]
    end
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI + Uvicorn |
| PDF Parsing | pypdf |
| Chunking | LangChain RecursiveCharacterTextSplitter |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) |
| Vector DB | ChromaDB (local, SQLite-backed) |
| Knowledge Graph | Neo4j + Cypher |
| LLM | Anthropic Claude (claude-opus-4-5) |
| Agent Orchestration | LangGraph |
| HITL Checkpointing | SQLite via LangGraph |
| Tracing | LangSmith |
| RAG Evaluation | RAGAs |
| MCP Server | Anthropic MCP Python SDK |
| Containerization | Docker Compose |

---

## Project Structure

```
edu_mind_ai/
├── backend/
│   ├── api/
│   │   └── main.py              # FastAPI app + all endpoints
│   ├── core/
│   │   ├── config.py            # Shared clients (Chroma, Neo4j, Anthropic, embedder)
│   │   ├── model.py             # Pydantic models + EduMindState TypedDict
│   │   ├── ingest.py            # PDF parsing, chunking, embedding, Chroma storage
│   │   ├── query.py             # Vector search + graph traversal + Claude answer
│   │   └── graph.py             # Entity extraction + Neo4j operations
│   ├── agents/
│   │   └── agents.py            # LangGraph nodes + graph definition
│   ├── mcp/
│   │   └── server.py            # MCP server exposing 3 tools to Claude Desktop
│   ├── eval/
│   │   ├── run_eval.py          # RAGAs evaluation script
│   │   ├── golden_dataset.json  # 30 Q&A pairs for evaluation
│   │   └── requirements-eval.txt
│   ├── requirements.txt
│   └── Dockerfile
├── docs/
│   ├── neo4j.png                # Knowledge graph screenshot
│   ├── langsmith.png            # LangSmith tracing screenshot
│   ├── ragas.png                # RAGAs eval scores screenshot
│   └── mcp.png                  # Claude Desktop MCP tool call screenshot
├── docker-compose.yml
└── README.md
```

---

## Setup

### Prerequisites
- Docker Desktop
- Anthropic API key

### Run

```bash
# Clone the repo
git clone https://github.com/codeshivamsi-sketch/edu_mind_ai_study_assistance.git
cd edu_mind_ai_study_assistance

# Add environment variables
cp backend/.env.example backend/.env
# Fill in your API keys in backend/.env

# Start all services
docker-compose up --build
```

### Environment Variables

```env
ANTHROPIC_API_KEY=your-key
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=password
LANGCHAIN_API_KEY=your-key
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=edumind
```

---

## Running Evaluation

```bash
# Create eval environment (Python 3.11 required)
cd backend/eval
python3.11 -m venv eval_venv
source eval_venv/bin/activate
pip install -r requirements-eval.txt

# Make sure Docker is running first
docker-compose up -d

# Run RAGAs evaluation
python run_eval.py
```

---

## API Endpoints

### Upload PDF
```bash
POST /upload
Content-Type: multipart/form-data

curl -X POST http://localhost:8000/upload \
  -F "file=@curriculum.pdf"

# Response
{"filename": "curriculum.pdf", "chunks": 21}
```

### Query (Agent)
```bash
POST /agent
Content-Type: application/json

# Answer a question
{"question": "what is RAG?"}

# Generate quiz
{"question": "quiz me on neural networks"}

# Summarize
{"question": "summarize embeddings chapter"}

# Response includes thread_id for HITL
{"intent": "quiz", "quiz_questions": [...], "thread_id": "uuid"}
```

### Evaluate (HITL)
```bash
POST /evaluate
Content-Type: application/json

{
  "thread_id": "uuid-from-agent-response",
  "user_answer": "your answer here"
}

# Response
{"evaluation": "Score: 7/10 — Great answer on..."}
```

### Health Check
```bash
GET /health
# {"status": "ok"}
```

---

## Phase Breakdown

### Phase 1 — RAG Pipeline
- PDF upload + text extraction
- Chunking with overlap for context preservation
- Local embeddings (no OpenAI cost)
- ChromaDB vector storage
- Semantic search + Claude answer generation with citations

### Phase 2 — Knowledge Graph
- Claude extracts entities and relationships from each chunk
- Stored in Neo4j as typed concept nodes and edges
- Hybrid retrieval — vector search + graph traversal merged into context
- Enables questions like "what should I learn before neural networks?"

![Neo4j](docs/neo4j.png)

### Phase 3 — Agentic Workflow with LangGraph
- Orchestrator classifies intent and routes to the right agent
- Retrieval Agent queries both ChromaDB and Neo4j
- Quiz Agent generates questions from retrieved content
- Evaluator Agent scores user answers with detailed feedback
- Summarizer Agent condenses content into study notes
- Human-in-the-loop: graph pauses after quiz, resumes after user answers
- SQLite checkpointing persists state between API calls
- LangSmith tracing for full observability

![LangSmith](docs/langsmith.png)

### Phase 4 — RAG Evaluation with RAGAs
- 30-question golden dataset covering all curriculum chapters
- Offline evaluation pipeline hitting the live Docker API
- Isolated eval environment (Python 3.11) to avoid dependency conflicts
- Four RAGAs metrics scored using Claude as judge LLM and local embeddings:

| Metric | Score | What it measures |
|--------|-------|-----------------|
| Faithfulness | 1.00 | Answer grounded in retrieved context — no hallucination |
| Answer Relevancy | 0.90 | Answer directly addresses the question |
| Context Precision | 0.70 | Retrieved chunks were relevant to the question |
| Context Recall | 1.00 | All needed information was present in retrieved chunks |

**Key finding:** Context precision at 0.70 indicates fixed-size chunking (500 chars) retrieves some noise alongside relevant chunks. Faithfulness and recall at 1.0 confirm the system never hallucinates and never misses needed information.

![RAGAs](docs/ragas.png)

### Phase 5 — MCP Server
- Exposed EduMind as an MCP server using the Anthropic MCP Python SDK
- Claude Desktop connects to the server and calls EduMind tools directly
- 3 tools registered:

| Tool | Description |
|------|-------------|
| `query_curriculum(question)` | RAG query over uploaded content — returns grounded answer with sources |
| `get_related_concepts(topic)` | Neo4j graph traversal — returns related concepts for a topic |
| `generate_quiz(topic, num_questions)` | Triggers Quiz Agent — returns quiz questions from curriculum |

- MCP server runs as a subprocess launched by Claude Desktop via stdio transport
- No extra HTTP server needed — communicates through stdin/stdout
- Claude Desktop automatically discovers and calls tools based on user intent

**Demo:** Open Claude Desktop → ask "quiz me on machine learning using my curriculum" → Claude calls `generate_quiz` → returns questions grounded in your uploaded PDF.

#### Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "edumind": {
      "command": "/path/to/edu_mind_ai/backend/venv/bin/python",
      "args": ["/path/to/edu_mind_ai/backend/mcp/server.py"]
    }
  }
}
```

Restart Claude Desktop. Make sure Docker is running first.

![MCP](docs/mcp.png)
