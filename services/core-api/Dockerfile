FROM python:3.13-slim

WORKDIR /app

COPY services/core-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY proto/notifications.proto ./proto/notifications.proto
RUN python -m grpc_tools.protoc -I proto --python_out=. --grpc_python_out=. proto/notifications.proto

COPY services/core-api/ .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
