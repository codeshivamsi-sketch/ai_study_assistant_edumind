from fastapi import FastAPI, UploadFile, File, Form, HTTPException
import os
import uuid
from typing import Optional
from core.ingest import save_pdf_on_disk, get_pdf_content, split_content_into_chunks, embed_chunks, store_in_chroma, ingest_graph
import chromadb
from core.model import QueryRequest, AgentRequest, EvaluateRequest
from core.queue_client import job_queue
from agents.agents import agent as langgraph_agent

app = FastAPI()

@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_pdf(file: UploadFile = File(...), document_id: Optional[str] = Form(None)):
    safe_filename = await save_pdf_on_disk(file)
    pdf_content = get_pdf_content(f"uploads/{safe_filename}")
    chunks = split_content_into_chunks(pdf_content)
    embeddings = embed_chunks(chunks)
    store_in_chroma(chunks, embeddings, document_id)
    ingest_graph(chunks)
    return {"filename": file.filename, "chunks": len(chunks), "document_id": document_id}


@app.post("/agent", status_code=202)
def agent_endpoint(request: AgentRequest):
    if not request.chat_id or not request.message_id:
        raise HTTPException(status_code=400, detail="chat_id and message_id are required")
    job_queue.enqueue(
        "core.jobs.run_agent_job",
        request.question,
        request.document_id,
        request.chat_id,
        request.message_id,
    )
    return {"accepted": True}


@app.post("/agent/sync")
def agent_sync_endpoint(request: QueryRequest):
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    result = langgraph_agent.invoke(
        {"question": request.question, "document_id": request.document_id},
        config=config,
    )
    return {**result, "thread_id": thread_id}


@app.post("/evaluate", status_code=202)
def evaluate_endpoint(request: EvaluateRequest):
    job_queue.enqueue(
        "core.jobs.run_evaluate_job",
        request.thread_id,
        request.user_answer,
        request.chat_id,
        request.message_id,
        request.quiz_id,
    )
    return {"accepted": True}
