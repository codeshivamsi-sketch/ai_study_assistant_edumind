from fastapi import FastAPI
from routes import router
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()
app.include_router(router)
Instrumentator().instrument(app).expose(app)

@app.get("/health")
def health():
    return { "status": "ok" }