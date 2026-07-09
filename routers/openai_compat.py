"""OpenAI-compatible API (/v1) so external tools (Continue, Aider, scripts
using the openai SDK) can use this server as a drop-in LLM provider.

Auth: Bearer <api key> generated per user via POST /api/users/me/api-key.
JWT session tokens are also accepted, so the web app could use it too.
"""

import json
import time
import uuid

import jwt
import requests
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

from database.db import get_conn
from routers.auth import SECRET_KEY, ALGORITHM
from services.llm_service import LLMService, OLLAMA_URL

router = APIRouter(prefix="/v1")


def get_v1_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()

    if token.startswith("sk-vibe-"):
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, name, email, role FROM users WHERE api_key = %s", (token,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return {"id": row[0], "name": row[1], "sub": row[2], "role": row[3]}

    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


class ChatMessage(BaseModel):
    role: str
    content: str


class CompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@router.get("/models")
async def list_models(user: dict = Depends(get_v1_user)):
    data = []
    try:
        res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        res.raise_for_status()
        for m in res.json().get("models", []):
            data.append({"id": m["name"], "object": "model", "owned_by": "ollama", "created": 0})
    except Exception as e:
        print(f"[v1] failed to list ollama models: {e}")
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id FROM models WHERE is_active IS DISTINCT FROM FALSE")
        for (mid,) in cur.fetchall():
            data.append({"id": mid, "object": "model", "owned_by": "vibe", "created": 0})
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[v1] failed to list presets: {e}")
    return {"object": "list", "data": data}


def _build_prompt(messages: List[ChatMessage]):
    system_parts = [m.content for m in messages if m.role == "system"]
    convo = [m for m in messages if m.role != "system"]
    system_prompt = "\n\n".join(system_parts) or None

    if len(convo) <= 1:
        query = convo[0].content if convo else ""
        return query, system_prompt

    lines = ["Conversation history:"]
    for m in convo[:-1]:
        lines.append(f"{'User' if m.role == 'user' else 'Assistant'}: {m.content}")
    lines.append(f"\nQuestion:\n{convo[-1].content}")
    return "\n".join(lines), system_prompt


def _resolve(model_id: str):
    from routers.chat import resolve_model
    resolved, preset_prompt, _, _ = resolve_model(model_id)
    return resolved, preset_prompt


@router.post("/chat/completions")
async def chat_completions(req: CompletionRequest, user: dict = Depends(get_v1_user)):
    resolved_model, preset_prompt = _resolve(req.model)
    query, system_prompt = _build_prompt(req.messages)
    if not system_prompt:
        system_prompt = preset_prompt

    options = {}
    if req.temperature is not None:
        options["temperature"] = req.temperature
    if req.max_tokens is not None:
        options["num_predict"] = req.max_tokens

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"
    created = int(time.time())
    llm = LLMService(model=resolved_model)

    if not req.stream:
        res = await llm.generate(query, system_prompt=system_prompt, options=options or None)
        stats = res.get("stats", {})
        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": req.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": res.get("response", "")},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": stats.get("prompt_eval_count", 0),
                "completion_tokens": stats.get("eval_count", 0),
                "total_tokens": stats.get("prompt_eval_count", 0) + stats.get("eval_count", 0),
            },
        }

    async def sse():
        base = {"id": completion_id, "object": "chat.completion.chunk", "created": created, "model": req.model}
        first = {**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]}
        yield f"data: {json.dumps(first)}\n\n"
        try:
            async for chunk in llm.generate_stream(query, system_prompt=system_prompt):
                token = chunk.get("response", "")
                if token:
                    ev = {**base, "choices": [{"index": 0, "delta": {"content": token}, "finish_reason": None}]}
                    yield f"data: {json.dumps(ev)}\n\n"
                if chunk.get("done"):
                    break
        except Exception as e:
            ev = {**base, "choices": [{"index": 0, "delta": {"content": f"\n[error: {e}]"}, "finish_reason": None}]}
            yield f"data: {json.dumps(ev)}\n\n"
        final = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
        yield f"data: {json.dumps(final)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")
