from fastapi import FastAPI
from routers import chat, upload, ws_chat, health, models

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="LLM OpenUI",
    version="1.0.0"
)

app = FastAPI()


# Register routers
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(ws_chat.router)
app.include_router(health.router)
app.include_router(models.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
@app.get("/")
def root():
    return {
        "status": "running",
        "message": "LLM OpenUI backend is live"
    }



