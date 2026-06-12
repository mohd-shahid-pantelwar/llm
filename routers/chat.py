import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from services.llm_service import LLMService
from services.rag_service import ask
from database.db import get_conn
from routers.users import get_current_user

router = APIRouter(prefix="/api")

def check_access(access_control: dict, owner_id: Optional[int], current_user: dict) -> bool:
    if current_user.get("role") == "admin":
        return True
    if owner_id is not None and owner_id == current_user.get("id"):
        return True
    if not access_control or access_control.get("type", "public") == "public":
        return True
    if access_control.get("type") == "private":
        access_list = access_control.get("access_list", [])
        for entry in access_list:
            if entry.get("type") == "user" and int(entry.get("id")) == int(current_user.get("id")):
                return True
    return False

from typing import Optional, List

class ChatMessage(BaseModel):
    sender: str
    content: str

class ChatRequest(BaseModel):
    query: str
    top_k: int = 5
    model: str
    use_rag: bool = False
    knowledge_id: Optional[str] = None
    file_id: Optional[str] = None
    system_prompt: Optional[str] = None
    stream: bool = False
    history: Optional[List[ChatMessage]] = None

def resolve_model(model_id: str) -> tuple[str, Optional[str], Optional[str]]:
    # If the model_id is already one of the base Ollama models, use it directly
    if model_id in ["gemma3:latest", "llama3:latest"]:
        return model_id, None, None

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
            knowledge_id = None
            if meta_data:
                if isinstance(meta_data, str):
                    try:
                        meta_data = json.loads(meta_data)
                    except Exception:
                        pass
                if isinstance(meta_data, dict):
                    system_prompt = meta_data.get("systemPrompt")
                    selected_knowledge = meta_data.get("selectedKnowledge", [])
                    if selected_knowledge and len(selected_knowledge) > 0:
                        # Extract the ID from the first attached knowledge
                        first_kb = selected_knowledge[0]
                        if isinstance(first_kb, dict) and "id" in first_kb:
                            knowledge_id = first_kb["id"]
            
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
                
            return resolved_base, system_prompt, knowledge_id
    except Exception as e:
        print("Error resolving model ID:", e)

    return "gemma3:latest", None, None

@router.post("/chat")
async def chat(req: ChatRequest, current_user: dict = Depends(get_current_user)):
    # 1. Check Model Access Control Permission
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("SELECT user_id, access_control FROM models WHERE id = %s", (req.model,))
        row = cur.fetchone()
        if row:
            owner_id, ac = row[0], row[1]
            if isinstance(ac, str):
                try:
                    ac = json.loads(ac)
                except Exception:
                    pass
            if ac:
                if not check_access(ac, owner_id, current_user):
                    cur.close()
                    conn.close()
                    raise HTTPException(status_code=403, detail="You do not have permission to access this model.")

        # 2. Check Knowledge base Access Control Permission
        if req.knowledge_id:
            cur.execute("SELECT user_id, access_control FROM knowledge WHERE id = %s", (req.knowledge_id,))
            row = cur.fetchone()
            if row:
                owner_id, ac = row[0], row[1]
                if isinstance(ac, str):
                    try:
                        ac = json.loads(ac)
                    except Exception:
                        pass
                if ac:
                    if not check_access(ac, owner_id, current_user):
                        cur.close()
                        conn.close()
                        raise HTTPException(status_code=403, detail="You do not have permission to access this knowledge base.")
    finally:
        cur.close()
        conn.close()

    resolved_model, preset_system_prompt, preset_knowledge_id = resolve_model(req.model)
    
    # Use request's system_prompt if provided, otherwise fall back to model preset's system prompt
    if req.system_prompt is not None:
        final_system_prompt = req.system_prompt if req.system_prompt.strip() else None
    else:
        final_system_prompt = preset_system_prompt

    # Use request's knowledge_id if provided, otherwise use the model's preset knowledge_id
    final_knowledge_id = req.knowledge_id if req.knowledge_id else preset_knowledge_id

    if req.stream:
        from fastapi.responses import StreamingResponse
        
        async def stream_generator():
            if req.use_rag or final_knowledge_id:
                from services.rag_service import ask_stream
                async for chunk in ask_stream(req.query, req.top_k, resolved_model, final_knowledge_id, file_id=req.file_id, system_prompt=final_system_prompt, history=req.history):
                    yield f"data: {json.dumps({'answer': chunk.get('response', ''), 'done': chunk.get('done', False), 'stats': chunk.get('stats', {}), 'sources': chunk.get('sources', [])})}\n\n"
            else:
                try:
                    llm = LLMService(model=resolved_model)
                    final_query = req.query
                    if req.history:
                        prompt_with_history = "Conversation history:\n"
                        for msg in req.history:
                            role = "User" if msg.sender == "user" else "Assistant"
                            prompt_with_history += f"{role}: {msg.content}\n"
                        prompt_with_history += f"\nQuestion:\n{req.query}"
                        final_query = prompt_with_history
                    async for chunk in llm.generate_stream(final_query, system_prompt=final_system_prompt):
                        yield f"data: {json.dumps({'answer': chunk.get('response', ''), 'done': chunk.get('done', False), 'stats': chunk.get('stats', {}), 'sources': []})}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'answer': f'⚠️ Error: {str(e)}', 'done': True, 'stats': {}, 'sources': []})}\n\n"

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    if req.use_rag or final_knowledge_id:
        return await ask(req.query, req.top_k, resolved_model, final_knowledge_id, file_id=req.file_id, system_prompt=final_system_prompt, history=req.history)
    import httpx
    try:
        llm = LLMService(model=resolved_model)
        final_query = req.query
        if req.history:
            prompt_with_history = "Conversation history:\n"
            for msg in req.history:
                role = "User" if msg.sender == "user" else "Assistant"
                prompt_with_history += f"{role}: {msg.content}\n"
            prompt_with_history += f"\nQuestion:\n{req.query}"
            final_query = prompt_with_history
        res_data = await llm.generate(final_query, system_prompt=final_system_prompt)
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