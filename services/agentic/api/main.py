from fastapi import FastAPI, UploadFile, File
import os
from core.ingest import save_pdf_on_disk, get_pdf_content, split_content_into_chunks, embed_chunks, store_in_chroma, ingest_graph
from core.query import embed_ques, get_searched_chunks_from_chroma, get_ans_from_claud, get_related_from_graph
import chromadb
from core.model import QueryRequest, AgentRequest, EvaluateRequest
from agents.agents import agent, evaluator_node
import uuid

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...)):
    await save_pdf_on_disk(file)
    pdf_content = get_pdf_content(f"uploads/{file.filename}")
    chunks = split_content_into_chunks(pdf_content)
    embeddings = embed_chunks(chunks)
    store_in_chroma(chunks, embeddings)
    ingest_graph(chunks)
    return {"filename": file.filename, "chunks": len(chunks)}


@app.post("/query")
def query_endpoint(request: QueryRequest):
    question = request.question
    question_embedding = embed_ques(question)
    chunks = get_searched_chunks_from_chroma(question_embedding)
    graph_concepts = get_related_from_graph(question)
    response = get_ans_from_claud(question, chunks, graph_concepts)
    return {
        "answer": response.content[0].text,
        "source_chunks": chunks,
        "related_concepts": graph_concepts
    }


@app.post("/agent")
def agent_endpoint(request: AgentRequest):
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    result = agent.invoke({"question": request.question}, config=config)
    return {**result, "thread_id": thread_id}


@app.post("/evaluate")
def evaluate_endpoint(request: EvaluateRequest):
    try:
        config = {"configurable":{"thread_id":request.thread_id}}

        current_state = agent.get_state(config)
        print("Current state: ", current_state)
        print("Next nodes:", current_state.next)

        agent.update_state(
            config,
            {"user_answer":request.user_answer},
            as_node="quiz"  # ← tells LangGraph this update comes from after quiz nod, — so it knows to run evaluate next, not restart from orchestrator.
        )

        # invoke() = give me the final answer
        # stream() = give me updates as each step completes

        print("Starting stream...")
        result = None
        for state in agent.stream( # stream() — runs graph and yields state after each node.
            None,  # None means "don't start fresh, resume from interrupt point."
            config=config
        ):
            print("State chunk:", state)
            result=state
        print("Stream done, result: ", result)

        print("Final result:", result)
        return {"evaluation":result.get("evaluate", {}).get("evaluation", "No evaluation")}
    except Exception as e:
        print("ERR: ", str(e))
        raise e
