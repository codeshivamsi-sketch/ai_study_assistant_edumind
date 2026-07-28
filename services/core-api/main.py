from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from routes import router
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3001", "http://localhost:3002", "http://localhost:3003",
        "http://localhost:3004", "http://localhost:3005",
        "http://localhost:3101", "http://localhost:3103", "http://localhost:3104", "http://localhost:3105",
    ],
    allow_credentials=False,  # no cookies — auth is a bare X-User-Id header
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
Instrumentator().instrument(app).expose(app)

@app.get("/health")
def health():
    return { "status": "ok" }