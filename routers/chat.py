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
    use_web_search: bool = False
    knowledge_id: Optional[str] = None
    file_id: Optional[str] = None
    system_prompt: Optional[str] = None
    stream: bool = False
    history: Optional[List[ChatMessage]] = None
    thread_id: Optional[str] = None

def resolve_model(model_id: str) -> tuple[str, Optional[str], Optional[str]]:
    # If the model_id is already one of the base Ollama models, use it directly
    if model_id in ["gemma3:latest", "llama3:latest"]:
        return model_id, None, None, []

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
            selected_tools = []
            if meta_data:
                if isinstance(meta_data, str):
                    try:
                        meta_data = json.loads(meta_data)
                    except Exception:
                        pass
                if isinstance(meta_data, dict):
                    system_prompt = meta_data.get("systemPrompt")
                    selected_tools = meta_data.get("selectedTools", [])
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
                
            return resolved_base, system_prompt, knowledge_id, selected_tools
    except Exception as e:
        print("Error resolving model ID:", e)

    return "gemma3:latest", None, None, []

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

    resolved_model, preset_system_prompt, preset_knowledge_id, selected_tools = resolve_model(req.model)
    
    # Use request's system_prompt if provided, otherwise fall back to model preset's system prompt
    if req.system_prompt is not None:
        final_system_prompt = req.system_prompt if req.system_prompt.strip() else None
    else:
        final_system_prompt = preset_system_prompt

    # Admin-configured global system prompt applies to every chat, ahead of
    # any per-request or per-model prompt.
    try:
        from database.redis import r as _redis
        global_prompt = _redis.get("admin:settings:globalSystemPrompt")
    except Exception:
        global_prompt = None
    if global_prompt:
        final_system_prompt = f"{global_prompt}\n\n{final_system_prompt}" if final_system_prompt else global_prompt

    # Per-user memories (OpenWebUI-style personalization)
    try:
        from routers.memories import get_user_memory_context
        memory_context = get_user_memory_context(current_user.get("id"))
    except Exception:
        memory_context = ""
    if memory_context:
        final_system_prompt = f"{final_system_prompt}\n\n{memory_context}" if final_system_prompt else memory_context

    # Use request's knowledge_id if provided, otherwise use the model's preset knowledge_id
    final_knowledge_id = req.knowledge_id if req.knowledge_id else preset_knowledge_id
    
    user_id = str(current_user.get("sub", ""))
    print(f"\n[Chat] Request for user_id: {user_id} | thread_id: {req.thread_id} | model: {req.model} | query: '{req.query}'")
    print(f"[Chat Debug] selected_tools: {[t.get('id') for t in selected_tools]}")

    tool_executed = False

    # Kick off web search first so the network I/O overlaps the
    # tool-routing LLM call below instead of running after it.
    web_search_task = None
    if req.use_web_search:
        import asyncio as _asyncio
        from services.web_search import search_web
        web_search_task = _asyncio.create_task(_asyncio.to_thread(search_web, req.query))

    # 3. Tool Routing Agent
    if selected_tools:
        import httpx
        tool_prompt = f"""You are a tool-routing assistant. The user has access to the following tools:
{json.dumps([{'name': t['title'], 'description': t['description'], 'id': t['id']} for t in selected_tools])}

User Query: "{req.query}"

Instructions:
1. VERY IMPORTANT: You must default to replying "NO" for 99% of queries!
2. If the user asks you to analyze, summarize, or answer a question about events/logs (e.g. "show me the AppArmor Denied events", "what is..."), you MUST reply EXACTLY "NO".
3. ONLY reply with the "soc-tool" ID if the user EXPLICITLY asks to "fetch NEW logs", "pull updates", or "run the script".
4. ONLY reply with the "agent-inventory-tool" ID if the user explicitly asks to "list all agents", "show registered agents", or "get complete agent inventory".
5. DO NOT explain your reasoning. Just output "NO" or the tool ID.

Decision:"""
        try:
            # Always use a stronger/faster base model for routing instead of a weak finetune if possible, but resolved_model is what we have
            tool_llm = LLMService(model=resolved_model)
            # Decision is one word (NO or a tool id): cap output tokens
            tool_res = await tool_llm.generate(tool_prompt, options={"num_predict": 12})
            tool_answer = tool_res.get("response", "").strip()
            print(f"🤖 [Tool Router] LLM Decision: '{tool_answer}'")
            
            tool_answer_lower = tool_answer.lower()
            # Strict check to avoid "I will not use soc-tool" triggering it
            if "no" in tool_answer_lower.split() or "no." in tool_answer_lower.split() or tool_answer_lower == "no":
                pass # Explicitly denied
            else:
                for t in selected_tools:
                    tool_id_lower = t['id'].lower()
                    if tool_id_lower == tool_answer_lower or tool_id_lower in tool_answer_lower.split():
                        print(f"🤖 [Agent] User requested tool {t['id']}, executing natively via workspace API...")
                    # Get the JWT token from the original request to authenticate the tool call
                    auth_header = req.model  # Not available directly, let's execute natively via DB!
                    
                    import psycopg2
                    conn = get_conn()
                    cur = conn.cursor()
                    cur.execute("SELECT content, access_control FROM tools WHERE id=%s", (t['id'],))
                    row = cur.fetchone()
                    cur.close()
                    conn.close()
                    
                    if row:
                        code = row[0]
                        access_control = row[1]
                        if isinstance(access_control, str):
                            access_control = json.loads(access_control)
                        valves = access_control.get("valves", {})
                        
                        # Auto-install requirements from docstring!
                        import re
                        import subprocess
                        import sys
                        req_match = re.search(r"requirements:\s*(.+)", code, re.IGNORECASE)
                        if req_match:
                            requirements_str = req_match.group(1).strip()
                            if requirements_str:
                                reqs = [r.strip() for r in requirements_str.split(',') if r.strip()]
                                print(f"📦 [Tool Router] Installing requirements: {reqs}")
                                for req_pkg in reqs:
                                    try:
                                        subprocess.check_call([sys.executable, "-m", "pip", "install", req_pkg])
                                    except Exception as pip_err:
                                        print(f"⚠️ Failed to install {req_pkg}: {pip_err}")
                        
                        tool_env = {}
                        exec(code, tool_env, tool_env)
                        tool_instance = tool_env['Tools']()
                        if hasattr(tool_instance, "valves"):
                            for k, v in valves.items():
                                setattr(tool_instance.valves, k, v)
                                
                        # Call the first bound method
                        import inspect
                        methods = [m for m in dir(tool_instance) if not m.startswith('_') and inspect.ismethod(getattr(tool_instance, m))]
                        if methods:
                            method = getattr(tool_instance, methods[0])
                            print(f"Calling method: {method.__name__}")
                            tool_result = method()
                            print(f"✅ Tool {t['id']} executed successfully!")
                            
                            # Append the tool result to the history so the LLM knows what happened!
                            tool_msg = ChatMessage(sender="system", content=f"Tool {t['title']} execution result:\n{tool_result}")
                            if req.history is None:
                                req.history = []
                            req.history.append(tool_msg)
                            tool_executed = True
        except Exception as e:
            print(f"Tool Router Error: {e}")

    # 4. Web search: inject results as context ahead of generation
    web_sources = []
    if web_search_task is not None:
        from services.web_search import format_results_for_prompt, results_as_sources
        results, search_error = await web_search_task
        if search_error:
            print(f"[Web Search] {search_error}")
        if results:
            print(f"[Web Search] {len(results)} results for: '{req.query}'")
            web_sources = results_as_sources(results)
            web_msg = ChatMessage(sender="system", content=format_results_for_prompt(results))
            if req.history is None:
                req.history = []
            req.history.append(web_msg)

    if req.stream:
        from fastapi.responses import StreamingResponse

        async def stream_generator():
            import asyncio
            if (req.use_rag or final_knowledge_id or "soc" in req.model.lower()) and not tool_executed:
                from services.rag_service import ask_stream
                gen = ask_stream(req.query, req.top_k, resolved_model, final_knowledge_id, file_id=req.file_id, system_prompt=final_system_prompt, history=req.history, user_id=user_id)
            else:
                llm = LLMService(model=resolved_model)
                final_query = req.query
                if req.history:
                    prompt_with_history = "Conversation history:\n"
                    for msg in req.history:
                        role = "System" if msg.sender == "system" else ("User" if msg.sender == "user" else "Assistant")
                        prompt_with_history += f"{role}: {msg.content}\n"
                    prompt_with_history += f"\nQuestion:\n{req.query}"
                    final_query = prompt_with_history
                gen = llm.generate_stream(final_query, system_prompt=final_system_prompt)
            
            try:
                iterator = gen.__aiter__()
                task = None
                while True:
                    try:
                        if task is None:
                            task = asyncio.create_task(iterator.__anext__())
                            
                        done, pending = await asyncio.wait([task], timeout=15.0)
                        
                        if done:
                            chunk = task.result()
                            task = None  # Reset task for the next chunk
                            yield f"data: {json.dumps({'answer': chunk.get('response', ''), 'done': chunk.get('done', False), 'stats': chunk.get('stats', {}), 'sources': web_sources + chunk.get('sources', [])})}\n\n"
                            if chunk.get('done'):
                                break
                        else:
                            # Timeout reached, but Ollama is still thinking! Task remains in pending state.
                            yield f"data: {json.dumps({'answer': '', 'done': False, 'stats': {}, 'sources': [], 'ping': True})}\n\n"
                    except StopAsyncIteration:
                        break
            except Exception as e:
                yield f"data: {json.dumps({'answer': f'⚠️ Error: {str(e)}', 'done': True, 'stats': {}, 'sources': []})}\n\n"
            finally:
                if 'task' in locals() and task is not None and not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                if hasattr(gen, 'aclose'):
                    try:
                        await gen.aclose()
                    except Exception:
                        pass

        return StreamingResponse(stream_generator(), media_type="text/event-stream")

    if req.use_rag or final_knowledge_id or "soc" in req.model.lower():
        result = await ask(req.query, req.top_k, resolved_model, final_knowledge_id, file_id=req.file_id, system_prompt=final_system_prompt, history=req.history, user_id=user_id)
        if web_sources and isinstance(result, dict):
            result["sources"] = web_sources + (result.get("sources") or [])
        return result
    
    import httpx
    try:
        llm = LLMService(model=resolved_model)
        final_query = req.query
        if req.history:
            prompt_with_history = "Conversation history:\n"
            for msg in req.history:
                role = "System" if msg.sender == "system" else ("User" if msg.sender == "user" else "Assistant")
                prompt_with_history += f"{role}: {msg.content}\n"
            prompt_with_history += f"\nQuestion:\n{req.query}"
            final_query = prompt_with_history
        res_data = await llm.generate(final_query, system_prompt=final_system_prompt)
        return {
            "query": req.query,
            "answer": res_data.get("response", ""),
            "stats": res_data.get("stats", {}),
            "sources": web_sources
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