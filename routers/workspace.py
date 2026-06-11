from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import time
from database.db import get_conn
from database.redis import clear_rag_cache
from routers.users import get_current_user

router = APIRouter(prefix="/api/workspace")

class WorkspaceItemCreate(BaseModel):
    id: str
    title: str
    description: Optional[str] = ""
    content: Optional[str] = ""

class WorkspaceItemUpdate(BaseModel):
    title: str
    description: Optional[str] = ""
    content: Optional[str] = ""

# ─── Shared helpers ───────────────────────────────────────────────────────────

def _get_items(table: str, user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"SELECT id, title, description, content, created_at FROM {table} WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {"id": r[0], "title": r[1], "description": r[2] or "", "content": r[3] or "", "author": "By Admin", "updated": "Just now"}
        for r in rows
    ]

def _upsert_item(table: str, item_id: str, user_id: int, title: str, description: str, content: str):
    conn = get_conn()
    cur = conn.cursor()
    now = int(time.time())
    cur.execute(f"SELECT id FROM {table} WHERE id = %s AND user_id = %s", (item_id, user_id))
    if cur.fetchone():
        cur.execute(
            f"UPDATE {table} SET title = %s, description = %s, content = %s WHERE id = %s AND user_id = %s",
            (title, description, content, item_id, user_id)
        )
    else:
        cur.execute(
            f"INSERT INTO {table} (id, user_id, title, description, content, created_at) VALUES (%s, %s, %s, %s, %s, %s)",
            (item_id, user_id, title, description, content, now)
        )
    conn.commit()
    cur.close()
    conn.close()
    if table == "knowledge":
        clear_rag_cache()
    return {"status": "success", "id": item_id}

def _delete_item(table: str, item_id: str, user_id: int, label: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"DELETE FROM {table} WHERE id = %s AND user_id = %s RETURNING id", (item_id, user_id))
    deleted = cur.fetchone()
    if not deleted:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"{label} not found")
    conn.commit()
    cur.close()
    conn.close()
    if table == "knowledge":
        clear_rag_cache()
    return {"status": "success"}

def _update_item(table: str, item_id: str, item: WorkspaceItemUpdate, user_id: int, label: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT id FROM {table} WHERE id = %s AND user_id = %s", (item_id, user_id))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"{label} not found")
    cur.execute(
        f"UPDATE {table} SET title = %s, description = %s, content = %s WHERE id = %s AND user_id = %s",
        (item.title, item.description, item.content, item_id, user_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    if table == "knowledge":
        clear_rag_cache()
    return {"status": "success", "id": item_id}

# ─── Prompts ─────────────────────────────────────────────────────────────────

@router.get("/prompts")
async def get_prompts(current_user: dict = Depends(get_current_user)):
    return _get_items("prompts", current_user["id"])

@router.post("/prompts")
async def create_prompt(item: WorkspaceItemCreate, current_user: dict = Depends(get_current_user)):
    return _upsert_item("prompts", item.id, current_user["id"], item.title, item.description, item.content)

@router.put("/prompts/{item_id}")
async def update_prompt(item_id: str, item: WorkspaceItemUpdate, current_user: dict = Depends(get_current_user)):
    return _update_item("prompts", item_id, item, current_user["id"], "Prompt")

@router.delete("/prompts/{item_id}")
async def delete_prompt(item_id: str, current_user: dict = Depends(get_current_user)):
    return _delete_item("prompts", item_id, current_user["id"], "Prompt")

# ─── Skills ──────────────────────────────────────────────────────────────────

@router.get("/skills")
async def get_skills(current_user: dict = Depends(get_current_user)):
    return _get_items("skills", current_user["id"])

@router.post("/skills")
async def create_skill(item: WorkspaceItemCreate, current_user: dict = Depends(get_current_user)):
    return _upsert_item("skills", item.id, current_user["id"], item.title, item.description, item.content)

@router.put("/skills/{item_id}")
async def update_skill(item_id: str, item: WorkspaceItemUpdate, current_user: dict = Depends(get_current_user)):
    return _update_item("skills", item_id, item, current_user["id"], "Skill")

@router.delete("/skills/{item_id}")
async def delete_skill(item_id: str, current_user: dict = Depends(get_current_user)):
    return _delete_item("skills", item_id, current_user["id"], "Skill")

# ─── Tools ───────────────────────────────────────────────────────────────────

@router.get("/tools")
async def get_tools(current_user: dict = Depends(get_current_user)):
    return _get_items("tools", current_user["id"])

@router.post("/tools")
async def create_tool(item: WorkspaceItemCreate, current_user: dict = Depends(get_current_user)):
    return _upsert_item("tools", item.id, current_user["id"], item.title, item.description, item.content)

@router.put("/tools/{item_id}")
async def update_tool(item_id: str, item: WorkspaceItemUpdate, current_user: dict = Depends(get_current_user)):
    return _update_item("tools", item_id, item, current_user["id"], "Tool")

@router.delete("/tools/{item_id}")
async def delete_tool(item_id: str, current_user: dict = Depends(get_current_user)):
    return _delete_item("tools", item_id, current_user["id"], "Tool")

# ─── Knowledge ───────────────────────────────────────────────────────────────

@router.get("/knowledge")
async def get_knowledge(current_user: dict = Depends(get_current_user)):
    return _get_items("knowledge", current_user["id"])

@router.post("/knowledge")
async def create_knowledge(item: WorkspaceItemCreate, current_user: dict = Depends(get_current_user)):
    return _upsert_item("knowledge", item.id, current_user["id"], item.title, item.description, item.content)

@router.put("/knowledge/{item_id}")
async def update_knowledge(item_id: str, item: WorkspaceItemUpdate, current_user: dict = Depends(get_current_user)):
    return _update_item("knowledge", item_id, item, current_user["id"], "Knowledge")

@router.delete("/knowledge/{item_id}")
async def delete_knowledge(item_id: str, current_user: dict = Depends(get_current_user)):
    return _delete_item("knowledge", item_id, current_user["id"], "Knowledge")
