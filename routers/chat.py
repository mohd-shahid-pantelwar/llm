import json
from typing import Optional
from fastapi import APIRouter
from pydantic import BaseModel
from services.llm_service import LLMService
from services.rag_service import ask
from database.db import get_conn

router = APIRouter(prefix="/api")

class ChatRequest(BaseModel):
    query: str
    top_k: int = 5
    model: str
    use_rag: bool = False
    knowledge_id: Optional[str] = None
    file_id: Optional[str] = None
    system_prompt: Optional[str] = None

def resolve_model(model_id: str) -> tuple[str, Optional[str]]:
    # If the model_id is already one of the base Ollama models, use it directly
    if model_id in ["gemma3:latest", "llama3:latest"]:
        return model_id, None

    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT base_model_id, meta FROM models WHERE id = %s", (model_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row:
            base_model_id, meta_data = row[0], row[1]
            system_prompt = None
            if meta_data:
                if isinstance(meta_data, str):
                    try:
                        meta_data = json.loads(meta_data)
                    except Exception:
                        pass
                if isinstance(meta_data, dict):
                    system_prompt = meta_data.get("systemPrompt")
            
            resolved_base = base_model_id
            if not resolved_base and meta_data and isinstance(meta_data, dict):
                provider = meta_data.get("provider")
                if provider:
                    p_lower = provider.lower()
                    if "gemma" in p_lower:
                        resolved_base = "gemma3:latest"
                    elif "llama" in p_lower:
                        resolved_base = "llama3:latest"
                    else:
                        resolved_base = provider
            if not resolved_base:
                resolved_base = "gemma3:latest"
                
            return resolved_base, system_prompt
    except Exception as e:
        print("Error resolving model ID:", e)

    return "gemma3:latest", None

@router.post("/chat")
async def chat(req: ChatRequest):
    resolved_model, preset_system_prompt = resolve_model(req.model)
    
    # Use request's system_prompt if provided, otherwise fall back to model preset's system prompt
    if req.system_prompt is not None:
        final_system_prompt = req.system_prompt if req.system_prompt.strip() else None
    else:
        final_system_prompt = preset_system_prompt

    if req.use_rag or req.knowledge_id:
        return await ask(req.query, req.top_k, resolved_model, req.knowledge_id, file_id=req.file_id, system_prompt=final_system_prompt)
    import httpx
    try:
        llm = LLMService(model=resolved_model)
        res_data = await llm.generate(req.query, system_prompt=final_system_prompt)
        return {
            "query": req.query,
            "answer": res_data.get("response", ""),
            "stats": res_data.get("stats", {}),
            "sources": []
        }
    except httpx.HTTPStatusError as e:
        from fastapi import HTTPException
        if e.response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Model '{resolved_model}' not found in Ollama. Please verify the model is downloaded.")
        raise HTTPException(status_code=500, detail=str(e))
    except httpx.ReadTimeout:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=504,
            detail=f"The model '{resolved_model}' took too long to respond. It may still be loading — please try again in a moment."
        )