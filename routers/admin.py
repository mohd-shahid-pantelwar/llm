import json
import os
import threading

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from database.db import get_conn
from database.redis import r
from routers.users import get_admin_user

router = APIRouter(prefix="/api")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

GLOBAL_SYSTEM_PROMPT_KEY = "admin:settings:globalSystemPrompt"
PULL_STATUS_KEY = "admin:models:pull:{name}"


# ─── Connections ───────────────────────────────────────────────────────────────

@router.get("/admin/connections/status")
async def connections_status(admin: dict = Depends(get_admin_user)):
    status = {"ollama_url": OLLAMA_URL, "reachable": False, "version": None}
    try:
        res = requests.get(f"{OLLAMA_URL}/api/version", timeout=5)
        res.raise_for_status()
        status["reachable"] = True
        status["version"] = res.json().get("version")
    except Exception as e:
        status["error"] = str(e)
    return status


# ─── General settings (global system prompt) ──────────────────────────────────

class GeneralSettings(BaseModel):
    globalSystemPrompt: str = ""


@router.get("/admin/settings/general")
async def get_general_settings(admin: dict = Depends(get_admin_user)):
    return {"globalSystemPrompt": r.get(GLOBAL_SYSTEM_PROMPT_KEY) or ""}


@router.post("/admin/settings/general")
async def save_general_settings(settings: GeneralSettings, admin: dict = Depends(get_admin_user)):
    if settings.globalSystemPrompt.strip():
        r.set(GLOBAL_SYSTEM_PROMPT_KEY, settings.globalSystemPrompt)
    else:
        r.delete(GLOBAL_SYSTEM_PROMPT_KEY)
    return {"status": "success"}


# ─── Web search settings ───────────────────────────────────────────────────────

class WebSearchSettings(BaseModel):
    provider: str = "duckduckgo"
    apiKey: str = ""
    googleCx: str = ""
    resultCount: int = 5


@router.get("/admin/settings/websearch")
async def get_websearch_settings(admin: dict = Depends(get_admin_user)):
    from services.web_search import get_search_settings
    settings = get_search_settings()
    # Never echo the API key back; report only whether one is stored.
    settings["hasApiKey"] = bool(settings.pop("apiKey"))
    return settings


@router.post("/admin/settings/websearch")
async def save_websearch_settings(settings: WebSearchSettings, admin: dict = Depends(get_admin_user)):
    if settings.provider not in ("duckduckgo", "brave", "google_pse"):
        raise HTTPException(status_code=400, detail="Unknown provider")
    from services.web_search import get_search_settings, save_search_settings
    # Empty apiKey means "keep the stored one" so admins can edit other fields.
    api_key = settings.apiKey or (get_search_settings()["apiKey"])
    save_search_settings(settings.provider, api_key, settings.googleCx, max(1, min(settings.resultCount, 10)))
    return {"status": "success"}


@router.post("/admin/settings/websearch/test")
async def test_websearch(admin: dict = Depends(get_admin_user)):
    import asyncio
    from services.web_search import search_web
    results, error = await asyncio.to_thread(search_web, "current weather")
    if error:
        raise HTTPException(status_code=502, detail=error)
    return {"status": "success", "resultCount": len(results), "first": results[0] if results else None}


# ─── Ollama model management ───────────────────────────────────────────────────

def _pull_model_worker(name: str):
    key = PULL_STATUS_KEY.format(name=name)
    try:
        with requests.post(f"{OLLAMA_URL}/api/pull", json={"model": name}, stream=True, timeout=3600) as res:
            res.raise_for_status()
            for line in res.iter_lines():
                if not line:
                    continue
                data = json.loads(line)
                status = {"status": data.get("status", "")}
                if data.get("total"):
                    status["total"] = data["total"]
                    status["completed"] = data.get("completed", 0)
                if data.get("error"):
                    status = {"status": "error", "error": data["error"]}
                r.set(key, json.dumps(status), ex=3600)
                if data.get("error"):
                    return
        r.set(key, json.dumps({"status": "success"}), ex=3600)
    except Exception as e:
        r.set(key, json.dumps({"status": "error", "error": str(e)}), ex=3600)


class PullRequest(BaseModel):
    name: str


@router.post("/admin/models/pull")
async def pull_model(req: PullRequest, admin: dict = Depends(get_admin_user)):
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Model name is required")
    key = PULL_STATUS_KEY.format(name=name)
    existing = r.get(key)
    if existing and json.loads(existing).get("status") not in ("success", "error"):
        return {"status": "already_pulling"}
    r.set(key, json.dumps({"status": "starting"}), ex=3600)
    threading.Thread(target=_pull_model_worker, args=(name,), daemon=True).start()
    return {"status": "started"}


@router.get("/admin/models/pull/{name}")
async def pull_status(name: str, admin: dict = Depends(get_admin_user)):
    raw = r.get(PULL_STATUS_KEY.format(name=name))
    return json.loads(raw) if raw else {"status": "unknown"}


@router.delete("/admin/models/{name}")
async def delete_model(name: str, admin: dict = Depends(get_admin_user)):
    try:
        res = requests.delete(f"{OLLAMA_URL}/api/delete", json={"model": name}, timeout=30)
        if res.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Model '{name}' not found on Ollama server")
        res.raise_for_status()
        return {"status": "success", "message": f"Model '{name}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Typo correction (SymSpell + char-LSTM) ────────────────────────────────────

@router.post("/admin/typo/train")
async def train_typo_model(admin: dict = Depends(get_admin_user)):
    from services import typo_correction
    raw = get_redis().get(typo_correction.STATUS_KEY)
    if raw and json.loads(raw).get("status") in ("building vocabulary", "training"):
        return {"status": "already_training"}
    threading.Thread(target=typo_correction.train, daemon=True).start()
    return {"status": "started"}


@router.get("/admin/typo/status")
async def typo_train_status(admin: dict = Depends(get_admin_user)):
    from services.typo_correction import STATUS_KEY
    raw = get_redis().get(STATUS_KEY)
    return json.loads(raw) if raw else {"status": "not_trained"}


class TypoTest(BaseModel):
    text: str


@router.post("/admin/typo/test")
async def typo_test(req: TypoTest, admin: dict = Depends(get_admin_user)):
    from services.typo_correction import correct_query
    return {"input": req.text, "corrected": correct_query(req.text)}


# ─── Database export ───────────────────────────────────────────────────────────

EXPORT_TABLES = {
    "users": "SELECT id, name, email, role FROM users",
    "chats": "SELECT * FROM chats",
    "folders": "SELECT * FROM folders",
    "feedback": "SELECT * FROM feedback",
    "notes": "SELECT * FROM notes",
}


@router.get("/admin/db/export")
async def export_database(admin: dict = Depends(get_admin_user)):
    conn = get_conn()
    cur = conn.cursor()
    export = {}
    try:
        for table, query in EXPORT_TABLES.items():
            try:
                cur.execute(query)
                cols = [d[0] for d in cur.description]
                export[table] = [
                    {c: (v.isoformat() if hasattr(v, "isoformat") else v) for c, v in zip(cols, row)}
                    for row in cur.fetchall()
                ]
            except Exception as e:
                conn.rollback()
                export[table] = {"error": str(e)}
    finally:
        cur.close()
        conn.close()
    return JSONResponse(
        content=export,
        headers={"Content-Disposition": "attachment; filename=vibe-ai-export.json"},
    )
