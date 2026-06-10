from fastapi import APIRouter
from pydantic import BaseModel
from services.rag_service import ask

router = APIRouter(prefix="/api")



class ChatRequest(BaseModel):
    query: str
    top_k: int = 5


@router.post("/chat")
async def chat(req: ChatRequest):
    return await ask(req.query, req.top_k)