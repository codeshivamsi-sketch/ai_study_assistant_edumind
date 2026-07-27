# services/agentic — context for AI agents

## Decisions
- Chroma vector search is scoped by `document_id`: `store_in_chroma`/`get_searched_chunks_from_chroma` tag chunks with `document_id` and filter on it when given, so retrieval can be limited to one document instead of the entire global collection. Callers that omit `document_id` still get the old unfiltered global search (back-compat for existing callers).
- The Neo4j knowledge graph is deliberately left global — no `document_id` on nodes/relationships, no Cypher filtering. A graph linking concepts *across* documents is treated as correct behavior, not a bug, and scoping it was assessed as materially more work than scoping Chroma; `related_concepts` in `/agent` responses may surface concepts from other documents.
- Re-uploading the same `document_id` is unsupported — Chroma raises on duplicate ids (no upsert/replace logic). Acceptable for now; needs real handling before document replacement/re-ingestion is supported.
