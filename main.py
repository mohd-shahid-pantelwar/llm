import os
from fastapi import FastAPI
from routers import chat, upload, ws_chat, health, models, auth, users, chats, folders, workspace, feedback, notes, admin, memories, openai_compat

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
app.include_router(memories.router)
app.include_router(openai_compat.router)

ALLOWED_ORIGINS = [os.environ.get("FRONTEND_URL", "http://localhost:3000")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Unhandled 500s bypass CORSMiddleware, so the browser reports them as
# "CORS Missing Allow-Origin" and hides the real error. Attach the CORS
# header to error responses too, so the actual status/message surfaces.
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


class CORSOnErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as e:
            import traceback
            traceback.print_exc()
            resp = JSONResponse(status_code=500, content={"detail": f"Internal server error: {e}"})
            origin = request.headers.get("origin")
            if origin in ALLOWED_ORIGINS:
                resp.headers["Access-Control-Allow-Origin"] = origin
                resp.headers["Access-Control-Allow-Credentials"] = "true"
            return resp


app.add_middleware(CORSOnErrorMiddleware)
@app.get("/")
def root():
    return {
        "status": "running",
        "message": "LLM OpenUI backend is live"
    }



