from pydantic import BaseModel
from typing import List, TypedDict

class QueryRequest(BaseModel):
    question: str


class EduMindState(TypedDict):
    question: str
    intent: str     # "answer", "quiz", "summarize", "evaluate"
    chunks: List[str]
    related_concepts: List[str]
    answer: str
    quiz_questions: List[str]
    summary: str
    user_answer: str
    evaluation: str


class AgentRequest(BaseModel):
    question: str


class EvaluateRequest(BaseModel):
    thread_id: str
    user_answer: str
