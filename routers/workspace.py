from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import time
import json
from database.db import get_conn
from database.redis import clear_rag_cache
from routers.users import get_current_user, get_admin_user

router = APIRouter(prefix="/api/workspace", dependencies=[Depends(get_admin_user)])

class WorkspaceItemCreate(BaseModel):
    id: str
    title: str
    description: Optional[str] = ""
    content: Optional[str] = ""
    access_control: Optional[dict] = None

class WorkspaceItemUpdate(BaseModel):
    title: str
    description: Optional[str] = ""
    content: Optional[str] = ""
    access_control: Optional[dict] = None

# ─── Shared helpers ───────────────────────────────────────────────────────────

def _get_items(table: str, user_id: int):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        f"SELECT id, title, description, content, created_at, access_control FROM {table} WHERE user_id = %s ORDER BY created_at DESC",
        (user_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [
        {
            "id": r[0], 
            "title": r[1], 
            "description": r[2] or "", 
            "content": r[3] or "", 
            "author": "By Admin", 
            "updated": "Just now",
            "access_control": r[5] if r[5] else {"type": "public", "allow_public_write": False, "access_list": []}
        }
        for r in rows
    ]

def _upsert_item(table: str, item_id: str, user_id: int, title: str, description: str, content: str, access_control: Optional[dict] = None):
    conn = get_conn()
    cur = conn.cursor()
    now = int(time.time())
    ac = json.dumps(access_control) if access_control else json.dumps({"type": "public", "allow_public_write": False, "access_list": []})
    cur.execute(f"SELECT id FROM {table} WHERE id = %s AND user_id = %s", (item_id, user_id))
    if cur.fetchone():
        cur.execute(
            f"UPDATE {table} SET title = %s, description = %s, content = %s, access_control = %s WHERE id = %s AND user_id = %s",
            (title, description, content, ac, item_id, user_id)
        )
    else:
        cur.execute(
            f"INSERT INTO {table} (id, user_id, title, description, content, created_at, access_control) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (item_id, user_id, title, description, content, now, ac)
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
    ac = json.dumps(item.access_control) if item.access_control else json.dumps({"type": "public", "allow_public_write": False, "access_list": []})
    cur.execute(
        f"UPDATE {table} SET title = %s, description = %s, content = %s, access_control = %s WHERE id = %s AND user_id = %s",
        (item.title, item.description, item.content, ac, item_id, user_id)
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
    return _upsert_item("prompts", item.id, current_user["id"], item.title, item.description, item.content, item.access_control)

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
    return _upsert_item("skills", item.id, current_user["id"], item.title, item.description, item.content, item.access_control)

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
    return _upsert_item("tools", item.id, current_user["id"], item.title, item.description, item.content, item.access_control)

@router.put("/tools/{item_id}")
async def update_tool(item_id: str, item: WorkspaceItemUpdate, current_user: dict = Depends(get_current_user)):
    return _update_item("tools", item_id, item, current_user["id"], "Tool")

@router.delete("/tools/{item_id}")
async def delete_tool(item_id: str, current_user: dict = Depends(get_current_user)):
    return _delete_item("tools", item_id, current_user["id"], "Tool")

@router.post("/tools/{item_id}/execute")
async def execute_tool(item_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT content, access_control FROM tools WHERE id = %s AND user_id = %s", (item_id, current_user["id"]))
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="Tool not found")
        
    code = row[0]
    access_control_str = row[1]
    if not code:
        raise HTTPException(status_code=400, detail="Tool has no code")
        
    import re
    import subprocess
    requirements = []
    req_match = re.search(r'requirements:\s*([^\n\r]+)', code, re.IGNORECASE)
    if req_match:
        reqs_str = req_match.group(1)
        requirements = [r.strip() for r in reqs_str.split(',') if r.strip()]
        
    if requirements:
        try:
            subprocess.run(["pip", "install"] + requirements, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise HTTPException(status_code=500, detail=f"Failed to install requirements: {e.stderr.decode('utf-8', errors='ignore')}")
            
    tool_env = {}
    try:
        from pydantic import BaseModel, Field
        tool_env["BaseModel"] = BaseModel
        tool_env["Field"] = Field
        tool_env["__builtins__"] = __builtins__
        exec(code, tool_env, tool_env)
        
        if 'Tools' not in tool_env:
            raise HTTPException(status_code=400, detail="Tool script must contain a class named 'Tools'")
            
        tool_instance = tool_env['Tools']()
        
        # Inject valves from database (stored in access_control)
        try:
            if access_control_str:
                if isinstance(access_control_str, dict):
                    ac_data = access_control_str
                else:
                    import json
                    ac_data = json.loads(access_control_str)
                    if isinstance(ac_data, str):
                        ac_data = json.loads(ac_data)
                
                saved_valves = ac_data.get("valves", {})
                
                # If the tool has a valves object, update it
                if hasattr(tool_instance, "valves"):
                    for k, v in saved_valves.items():
                        setattr(tool_instance.valves, k, v)
        except Exception as ve:
            print("Failed to inject valves:", ve)
            
        method_name = payload.get("method_name")
        if not method_name:
            methods = [m for m in dir(tool_instance) if not m.startswith('_') and callable(getattr(tool_instance, m)) and m != 'valves']
            if not methods:
                raise HTTPException(status_code=400, detail="No callable methods found in Tools class")
            method_name = methods[0]
            
        method = getattr(tool_instance, method_name)
        kwargs = payload.get("kwargs", {})
        
        import inspect
        if inspect.iscoroutinefunction(method):
            result = await method(**kwargs)
        else:
            result = method(**kwargs)
            
        return {"status": "success", "result": result}
        
    except Exception as e:
        import traceback
        tb_str = traceback.format_exc()
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {str(e)}\n\nTraceback:\n{tb_str}")

# ─── Knowledge ───────────────────────────────────────────────────────────────

@router.get("/knowledge")
async def get_knowledge(current_user: dict = Depends(get_current_user)):
    return _get_items("knowledge", current_user["id"])

@router.post("/knowledge")
async def create_knowledge(item: WorkspaceItemCreate, current_user: dict = Depends(get_current_user)):
    return _upsert_item("knowledge", item.id, current_user["id"], item.title, item.description, item.content, item.access_control)

@router.put("/knowledge/{item_id}")
async def update_knowledge(item_id: str, item: WorkspaceItemUpdate, current_user: dict = Depends(get_current_user)):
    return _update_item("knowledge", item_id, item, current_user["id"], "Knowledge")

@router.delete("/knowledge/{item_id}")
async def delete_knowledge(item_id: str, current_user: dict = Depends(get_current_user)):
    return _delete_item("knowledge", item_id, current_user["id"], "Knowledge")
