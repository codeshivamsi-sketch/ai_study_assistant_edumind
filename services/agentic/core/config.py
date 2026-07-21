from dotenv import load_dotenv
import chromadb
from sentence_transformers import SentenceTransformer
from anthropic import Anthropic
import os
from neo4j import GraphDatabase


load_dotenv()
chroma_client = chromadb.PersistentClient(path="chroma_db")
collection = chroma_client.get_or_create_collection("pdf_chunks")
model = SentenceTransformer("all-MiniLM-L6-v2")
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
neo4j_driver = GraphDatabase.driver(
    os.getenv("NEO4J_URI"),
    auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
)
