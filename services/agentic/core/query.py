from core.config import collection, model, anthropic_client
import os
from core.graph import extract_entities, get_related_concepts
import json

def embed_ques(question: str):
    question_embedding = model.encode(question).tolist()
    return question_embedding

def get_searched_chunks_from_chroma(question_embedding):
    results = collection.query(
        query_embeddings=[question_embedding],
        n_results=3
    )
    chunks = results["documents"][0]
    print("Chunks from chroma: ", chunks)
    return chunks

def get_related_from_graph(question: str):
    entities_json = extract_entities(question)
    entities = json.loads(entities_json)["entities"]

    graph_concepts = []
    for entity in entities:
        related = get_related_concepts(entity)
        graph_concepts.extend(related)

    print("Found these related concepts in GraphDB: ", graph_concepts)
    return graph_concepts



def get_ans_from_claud(question, chunks, graph_concepts):
    context = "\n\n".join(chunks)

    if graph_concepts:
        context += "\n\nRelated concepts from knowledge graph: " + ", ".join(graph_concepts)


    prompt="You are a helpful assistant. Answer the question using only the context provided. Cite which part of the context you used."
    grouding_context=f"Context:\n{context}\n\nQuestion: {question}"

    response = anthropic_client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        system=prompt,
        messages=[
            {
                "role": "user",
                "content": grouding_context
            }
        ]
    )
    return response
