from pydantic import BaseModel
from typing import List, Optional, TypedDict

class QueryRequest(BaseModel):
    question: str
    document_id: Optional[str] = None


class EduMindState(TypedDict):
    question: str
    document_id: str
    intent: str     # "answer", "quiz", "summarize", "evaluate"
    chunks: List[str]
    related_concepts: List[str]
    answer: str
    quiz_questions: List[str]
    summary: str
    user_answer: str
    score: float
    feedback: str


class AgentRequest(BaseModel):
    question: str
    document_id: Optional[str] = None
    chat_id: Optional[str] = None
    message_id: Optional[str] = None


class EvaluateRequest(BaseModel):
    thread_id: str
    user_answer: str
    chat_id: str
    message_id: str
    quiz_id: str
