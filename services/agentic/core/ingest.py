from pypdf import PdfReader
from langchain_text_splitters import RecursiveCharacterTextSplitter
import os
from core.config import model, collection
from core.graph import extract_entities, store_entities

async def save_pdf_on_disk(file):
    contents = await file.read()
    os.makedirs("uploads", exist_ok=True)
    safe_filename = os.path.basename(file.filename)
    with open(f"uploads/{safe_filename}", "wb") as f:
        f.write(contents)
    return safe_filename


def get_pdf_content(filename: str):
    reader = PdfReader(filename)
    full_text = ""
    for page in reader.pages:
        full_text += page.extract_text()
    return full_text

def split_content_into_chunks(pdf_content: str):
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=50)
    chunks = splitter.split_text(pdf_content)
    print(f"Spiltted into: {len(chunks)} chunks")
    return chunks


def embed_chunks(chunks: list[str]):
    embeddings = model.encode(chunks)
    return embeddings.tolist()


def store_in_chroma(chunks: list[str], embeddings: list, document_id: str | None = None):
    if document_id:
        ids = [f"{document_id}-{i}" for i in range(len(chunks))]
        metadatas = [{"document_id": document_id} for _ in chunks]
        collection.add(documents=chunks, embeddings=embeddings, ids=ids, metadatas=metadatas)
    else:
        collection.add(
            documents=chunks,
            embeddings=embeddings,
            ids=[str(i) for i in range(len(chunks))]
        )


def ingest_graph(chunks: list[str]):
    for chunk in chunks:
        entities_json = extract_entities(chunk)
        store_entities(entities_json)
        print(f"Stored entities for chunk: {chunk}")
