from fastapi import APIRouter
from pydantic import BaseModel
from services.llm_service import LLMService
from services.rag_service import ask

router = APIRouter(prefix="/api")

class ChatRequest(BaseModel):
    query: str
    top_k: int = 5
    model: str
    use_rag: bool = False

@router.post("/chat")
async def chat(req: ChatRequest):
    if req.use_rag:
        return await ask(req.query, req.top_k, req.model)
    import httpx
    try:
        llm = LLMService(model=req.model)
        answer = await llm.generate(req.query)
        return {
            "query": req.query,
            "answer": answer,
            "sources": []
        }
    except httpx.HTTPStatusError as e:
        from fastapi import HTTPException
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Model '{req.model}' not found in Ollama. Please verify the model is downloaded.")
        raise HTTPException(status_code=500, detail=str(e))