# AI Study Assistant - Edumind

Upload a PDF, chat with it — Q&A, summaries, quiz generation & auto-grading — powered by multi-agent RAG (LangGraph, MCP, evals) with a knowledge graph, an event-driven distributed backend for async LLM workloads, and a micro-frontend UI (Webpack Module Federation).

![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white)
![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=flat&logo=pydantic&logoColor=white)
![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-D71F00?style=flat)
![Alembic](https://img.shields.io/badge/Alembic-6BA81E?style=flat)
![pytest](https://img.shields.io/badge/pytest-0A9EDC?style=flat&logo=pytest&logoColor=white)
![Fastify](https://img.shields.io/badge/Fastify-000000?style=flat&logo=fastify&logoColor=white)
![Node.js](https://img.shields.io/badge/Node.js-339933?style=flat&logo=nodedotjs&logoColor=white)
![Zod](https://img.shields.io/badge/Zod-3E67B1?style=flat&logo=zod&logoColor=white)
![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?style=flat&logo=typescript&logoColor=white)
![React](https://img.shields.io/badge/React-61DAFB?style=flat&logo=react&logoColor=black)
![React Router](https://img.shields.io/badge/React_Router-CA4245?style=flat&logo=reactrouter&logoColor=white)
![Webpack](https://img.shields.io/badge/Webpack-8DD6F9?style=flat&logo=webpack&logoColor=black)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-4169E1?style=flat&logo=postgresql&logoColor=white)
![Redis](https://img.shields.io/badge/Redis-DC382D?style=flat&logo=redis&logoColor=white)
![Celery](https://img.shields.io/badge/Celery-37814A?style=flat&logo=celery&logoColor=white)
![BullMQ](https://img.shields.io/badge/BullMQ-DC382D?style=flat)
![Neo4j](https://img.shields.io/badge/Neo4j-4581C3?style=flat&logo=neo4j&logoColor=white)
![ChromaDB](https://img.shields.io/badge/ChromaDB-FF6B35?style=flat)
![Claude](https://img.shields.io/badge/Claude-D97757?style=flat&logo=anthropic&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1C3C3C?style=flat&logo=langchain&logoColor=white)
![LangSmith](https://img.shields.io/badge/LangSmith-F5A623?style=flat)
![RAGAs](https://img.shields.io/badge/RAGAs-6C3483?style=flat)
![MCP](https://img.shields.io/badge/MCP-000000?style=flat&logo=anthropic&logoColor=white)
![Prisma](https://img.shields.io/badge/Prisma-2D3748?style=flat&logo=prisma&logoColor=white)
![Prometheus](https://img.shields.io/badge/Prometheus-E6522C?style=flat&logo=prometheus&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-F46800?style=flat&logo=grafana&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-2496ED?style=flat&logo=docker&logoColor=white)

## High-Level Design

```mermaid
flowchart TD
    FE[["Frontend\nModule Federation · :3001"]]
    Core[["Core API\nFastAPI · :8000"]]
    Notif[["Notifications\nFastify + gRPC · :5000/5001"]]
    Agentic[["Agentic\nFastAPI + LangGraph · :8002"]]
    PG[("Postgres\nedumind")]
    Redis[("Redis")]
    Claude(["Anthropic Claude"])

    FE -->|X-User-Id| Core
    FE -.poll.-> Notif
    Core --> PG
    Core <-->|upload sync · agent/evaluate async| Agentic
    Core -->|Celery → gRPC| Notif
    Notif --> PG
    Agentic --> Redis
    Agentic --> Claude
```

Everything else — Neo4j, Chroma, Prometheus/Grafana, the MCP server — lives inside `Agentic`/`Core API`; see the per-service diagrams below.

## Services

### Frontend

```mermaid
flowchart TD
    Browser --> Shell["shell :3001\nrouter · SessionContext (X-User-Id)"]
    Shell --> Manifest[["remotes.json"]]
    Shell -->|Module Federation| DS["design-system :3002"]
    Shell -->|Module Federation| Chat["remote-chat :3004"]
    Shell -->|Module Federation| RN["remote-notifications :3005"]
    Chat --> CoreAPI[["core-api"]]
    RN --> CoreAPI
    RN -.poll.-> NotifSvc[["notifications"]]
```

### Core API

```mermaid
flowchart TD
    Client -->|X-User-Id| Routes["routes.py"]
    Routes --> Identity["identity.py\n404, never 403"]
    Routes --> DB[("Postgres")]
    Routes -->|sync upload ·\nasync agent/evaluate| AC["agentic_client.py"] --> Agentic[["agentic"]]
    Routes -->|send_task| CW["worker.py\nCelery: notify_quiz_ready"]
    CW --> GC["grpc_client.py"] --> NotifSvc[["notifications"]]
    Routes -.->|/metrics| Prom[["Prometheus"]]
```

### Notifications

```mermaid
flowchart TD
    CoreWorker[["core-api Celery worker"]] -->|gRPC| GrpcServer["grpc/server.ts"]
    GrpcServer --> BullMQ[("Redis: BullMQ")]
    BullMQ --> JobWorker["jobs/notifyQuizReady.ts"] --> DB[("Postgres: notifications")]
    Client -->|X-User-Id| HTTP["routes.ts"] --> DB
```

### Agentic

```mermaid
flowchart TD
    Caller[["core-api / MCP"]]

    subgraph API ["api/main.py :8002"]
        Upload["POST /upload\nsync"]
        AgentEp["POST /agent\nenqueue, 202"]
        EvalEp["POST /evaluate\nenqueue, 202"]
    end

    RQ[("Redis: RQ")]

    subgraph Worker ["agentic-worker"]
        Jobs["run_agent_job / run_evaluate_job"]
    end

    Graph["LangGraph agent\n(see below)"]
    Chroma[("Chroma")]
    Neo4j[("Neo4j")]
    SQLite[("SQLite checkpoints")]
    Claude(["Anthropic Claude"])

    Caller --> Upload --> Chroma
    Upload --> Neo4j
    Upload --> Claude
    Caller --> AgentEp --> RQ
    Caller --> EvalEp --> RQ
    RQ --> Jobs --> Graph
    Graph --> Chroma
    Graph --> Neo4j
    Graph --> Claude
    Graph --> SQLite
    Jobs -->|callback| Caller
```
**Agent Graph — LangGraph state machine** (`agents/agents.py`):

```mermaid
flowchart TD
    Entry(["entry"]) --> O["orchestrator\nclassify intent"]
    O --> R["retrieval\nChroma + Neo4j"]
    R -->|answer| A["answer_node"]
    R -->|quiz| Q["quiz_node"]
    R -->|summarize| S["summarizer_node"]
    R -.->|"evaluate (dead — never classified)"| Ev
    Q ==>|"interrupt_after=['quiz']\nresumes via POST /evaluate"| Ev["evaluator_node"]
    A --> End(["END"])
    S --> End
    Ev --> End
```

## ER Diagram (Postgres)

```mermaid
erDiagram
    USERS ||--o{ DOCUMENTS : owns
    USERS ||--o{ CHATS : owns
    USERS ||--o{ QUIZ_ATTEMPTS : attempts
    DOCUMENTS ||--o| CHATS : "1:1, unique document_id"
    DOCUMENTS ||--o{ QUIZZES : contains
    CHATS ||--o{ MESSAGES : contains
    QUIZZES ||--o{ QUIZ_ATTEMPTS : "RESTRICT, not CASCADE"
    QUIZZES ||--o{ MESSAGES : "quiz_id, SET NULL"
    USERS ||--o{ NOTIFICATIONS : "user_id, no FK (Prisma)"

    USERS {
        uuid id PK
        string email UK
        string name
    }
    DOCUMENTS {
        uuid id PK
        uuid user_id FK
        string status "uploaded/processing/ready/failed"
    }
    CHATS {
        uuid id PK
        uuid user_id FK
        uuid document_id FK "unique"
    }
    MESSAGES {
        uuid id PK
        uuid chat_id FK
        string role "user/assistant"
        uuid quiz_id FK "nullable"
    }
    QUIZZES {
        uuid id PK
        uuid document_id FK
        jsonb questions
        string thread_id "LangGraph"
    }
    QUIZ_ATTEMPTS {
        uuid id PK
        uuid quiz_id FK
        uuid user_id FK
        numeric score
    }
    NOTIFICATIONS {
        uuid id PK
        uuid user_id "Prisma-managed"
        boolean read
    }
```

One `edumind` database, two migration tools: Alembic owns everything except `notifications`, which Prisma owns — no cross-schema FK between them.

## Flows

### Upload

```mermaid
sequenceDiagram
    participant C as Client
    participant Core as core-api
    participant PG as Postgres
    participant Agentic as agentic
    participant Chroma
    participant Neo4j
    participant Claude as Anthropic Claude

    C->>Core: POST /documents (multipart: title + file)
    Core->>PG: INSERT documents (status=uploaded → processing)
    Core->>Agentic: POST /upload (file, document_id) — sync, waits
    Agentic->>Agentic: extract text, chunk, embed
    Agentic->>Chroma: store chunk embeddings
    loop per chunk
        Agentic->>Claude: extract entities/relationships
        Agentic->>Neo4j: merge concept graph
    end
    Agentic-->>Core: 200 {chunks, document_id}
    Core->>PG: UPDATE documents SET status=ready (or failed)
    Core-->>C: 200 document
```

### Message (ask / quiz / summarize)

```mermaid
sequenceDiagram
    participant C as Client
    participant Core as core-api
    participant PG as Postgres
    participant Agentic as agentic
    participant RQ as Redis (RQ)
    participant Worker as agentic-worker
    participant Chroma
    participant Neo4j
    participant Claude as Anthropic Claude
    participant CeleryR as Redis (Celery)
    participant CW as Celery worker
    participant Notif as notifications (gRPC)

    C->>Core: POST /chats/{id}/messages {content}
    Core->>PG: INSERT messages (role=user)
    Core->>Agentic: POST /agent {question, document_id, chat_id, message_id}
    Agentic->>RQ: enqueue run_agent_job
    Agentic-->>Core: 202 accepted
    Core-->>C: 202 {user_message}

    RQ->>Worker: dequeue run_agent_job
    Worker->>Claude: classify intent (ask / quiz / summarize)
    Worker->>Chroma: retrieve relevant chunks
    Worker->>Neo4j: fetch related concepts
    Worker->>Claude: generate answer / quiz / summary
    Worker->>Core: POST /internal/chat-answers {result}
    Core->>PG: INSERT messages (role=assistant) [+ quizzes if intent=quiz]
    Core->>CeleryR: send_task notify_quiz_ready
    CeleryR->>CW: dequeue
    CW->>Notif: gRPC NotifyQuizReady
```

### Evaluate (quiz answer)

```mermaid
sequenceDiagram
    participant C as Client
    participant Core as core-api
    participant PG as Postgres
    participant Agentic as agentic
    participant RQ as Redis (RQ)
    participant Worker as agentic-worker
    participant Claude as Anthropic Claude
    participant CeleryR as Redis (Celery)
    participant CW as Celery worker
    participant Notif as notifications (gRPC)

    C->>Core: POST /chats/{id}/messages {content: answer, intent: quiz_answer, quiz_id}
    Core->>PG: verify quiz ownership + thread_id, INSERT messages (role=user)
    Core->>Agentic: POST /evaluate {thread_id, user_answer, quiz_id}
    Agentic->>RQ: enqueue run_evaluate_job
    Agentic-->>Core: 202 accepted
    Core-->>C: 202 {user_message}

    RQ->>Worker: dequeue run_evaluate_job
    Worker->>Worker: resume paused thread (as_node="quiz")
    Worker->>Claude: evaluate_node — score + feedback
    Worker->>Core: POST /internal/chat-answers {score, feedback}
    Core->>PG: INSERT messages (role=assistant, content=feedback)
    Core->>PG: INSERT quiz_attempts (score, feedback)
    Core->>CeleryR: send_task notify_quiz_ready
    CeleryR->>CW: dequeue
    CW->>Notif: gRPC NotifyQuizReady
```

Full hand-traced versions (exact function/table names, error branches, retry behavior) are in `docs/architecture.md`.

## Running Locally

```bash
cp services/agentic/.env.example services/agentic/.env   # add ANTHROPIC_API_KEY
make up                                                  # docker-compose up --build, every service
cd services/core-api && alembic upgrade head              # core-api tables
cd services/notifications && npx prisma migrate deploy    # notifications table
```

## Observability

| | URL |
|---|---|
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |

`core-api` exposes `/metrics`, scraped every 15s.

![Grafana Dashboard](docs/grafana_dashboard.png)

Every LangGraph node run is traced in LangSmith.
![LangSmith trace](services/agentic/docs/langsmith.png)

## Testing

```bash
cd services/core-api && pytest tests/ -v        # needs postgres running (make up)
cd services/notifications && npm test
```

**RAGAs eval** (`services/agentic/eval`, 30-question golden dataset, Claude as judge):

| Metric | Score |
|--------|-------|
| Faithfulness | 1.00 |
| Answer Relevancy | 0.90 |
| Context Precision | 0.70 |
| Context Recall | 1.00 |

![RAGAs evaluation scores](services/agentic/docs/ragas.png)

## MCP

| Tool | Description |
|------|-------------|
| `query_curriculum(question)` | grounded answer |
| `get_related_concepts(topic)` | related concepts from the graph |
| `generate_quiz(topic, num_questions)` | quiz from curriculum |

`docker compose up` starts `mcp-server` on `:8003` (streamable-http), add below to `claude_desktop_config.json` in Claude desktop, then restart:
```json
{
  "mcpServers": {
    "edumind": { "url": "http://localhost:8003/mcp" }
  }
}
```

![Claude MCP tool call](services/agentic/docs/mcp.png)
