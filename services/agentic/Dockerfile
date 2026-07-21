FROM python:3.11

WORKDIR /app

COPY requirements.txt .
COPY eval/requirements-eval.txt eval/requirements-eval.txt
RUN pip install -r requirements.txt -r eval/requirements-eval.txt

# Pre-download the model during build
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

# agents/agents.py does sqlite3.connect("checkpoints.db", ...) - a relative
# path resolving to /app/checkpoints.db (a FILE). Docker's named-volume
# mount only preserves a mount target as a file if a regular file already
# exists there in the image when the container is first created -
# otherwise it silently creates a directory instead, which would break
# sqlite3.connect() outright. This line exists so the docker-compose
# volume mount in Task 3 works correctly.
RUN touch checkpoints.db

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]