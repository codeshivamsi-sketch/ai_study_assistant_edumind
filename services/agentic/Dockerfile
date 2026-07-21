FROM python:3.11

WORKDIR /app

COPY requirements.txt .
COPY eval/requirements-eval.txt eval/requirements-eval.txt
RUN pip install -r requirements.txt -r eval/requirements-eval.txt

# Pre-download the model during build
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

COPY . .

# agents/agents.py does sqlite3.connect("checkpoints.db", ...) - a relative
# path resolving to /app/checkpoints.db (a FILE). Named-volume mounts onto
# a single file are unreliable across Docker Engine versions/snapshotter
# backends (some silently turn the mount target into a directory even
# when a real file exists there at image-build time; on containerd-
# snapshotter backends it can fail container creation outright with
# "is not directory"). Mounting onto a plain directory is the universally
# supported case, so /data is a real directory the volume mounts onto,
# and checkpoints.db becomes a symlink into it - sqlite3.connect()
# follows the symlink transparently and creates the real file inside the
# mounted, persisted directory. No application code changes needed.
RUN mkdir -p /data && rm -f checkpoints.db && ln -s /data/checkpoints.db checkpoints.db

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]