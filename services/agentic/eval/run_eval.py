import json
import os
import requests
from datasets import Dataset
from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
from langchain_anthropic import ChatAnthropic
from langchain_community.embeddings import HuggingFaceEmbeddings
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from dotenv import load_dotenv

load_dotenv("../.env")
print("KEY: ", os.getenv("ANTHROPIC_API_KEY"))

# Judge LLM → Claude
llm = LangchainLLMWrapper(ChatAnthropic(
    model="claude-opus-4-5",
    anthropic_api_key=os.getenv("ANTHROPIC_API_KEY")
))

# Embeddings → local sentence-transformers (no OpenAI needed)
embeddings = LangchainEmbeddingsWrapper(
    HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
)

with open("golden_dataset.json") as f:
    golden = json.load(f)
    golden = golden[:5]

questions, answers, contexts, ground_truths = [], [], [], []

for item in golden:
    question = item["question"]
    try:
        response = requests.post("http://localhost:8000/query", json={"question": question}, timeout=30)
        if response.status_code != 200 or not response.text:
            print(f"SKIP (status {response.status_code}): {question[:50]}")
            continue
        result = response.json()
        questions.append(question)
        answers.append(result["answer"])
        contexts.append(result["source_chunks"])
        ground_truths.append(item["ground_truth"])
        print(f"Done: {question[:50]}...")
    except Exception as e:
        print(f"SKIP (error: {e}): {question[:50]}")
        continue

print(f"\nCollected {len(questions)} responses. Running RAGAs...")

dataset = Dataset.from_dict({
    "question": questions,
    "answer": answers,
    "contexts": contexts,
    "ground_truth": ground_truths
})

# faithfulness — compares answer vs contexts (is answer grounded in chunks?)
# answer_relevancy — compares answer vs question (does answer address the question?)
# context_precision — compares contexts vs question (are retrieved chunks relevant?)
# context_recall — compares contexts vs ground_truth (did we retrieve everything needed?) ← uses ground_truth

result = evaluate(
    dataset,
    metrics=[
        faithfulness, 
        answer_relevancy, 
        context_precision, 
        context_recall
    ],
    llm=llm,
    embeddings=embeddings
)
print("\n=== RAGAS SCORES ===")
print(result)