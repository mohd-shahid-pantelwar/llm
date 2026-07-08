import os
from fastapi import FastAPI
from routers import chat, upload, ws_chat, health, models, auth, users, chats, folders, workspace, feedback, notes, admin

from fastapi.middleware.cors import CORSMiddleware

from contextlib import asynccontextmanager
from init_db import init_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize the database
    init_db()
    print("Database tables initialized.")
    yield

app = FastAPI(
    title="LLM OpenUI",
    version="1.0.0",
    lifespan=lifespan
)


# Register routers
app.include_router(chat.router)
app.include_router(upload.router)
app.include_router(ws_chat.router)
app.include_router(health.router)
app.include_router(models.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(chats.router)
app.include_router(folders.router)
app.include_router(workspace.router)
app.include_router(feedback.router)
app.include_router(notes.router)
app.include_router(admin.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.environ.get("FRONTEND_URL", "http://localhost:3000")],
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



