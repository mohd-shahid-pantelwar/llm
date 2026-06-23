from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import time
import json
from database.db import get_conn
from database.redis import clear_rag_cache
from routers.users import get_current_user, get_admin_user

router = APIRouter(prefix="/api/workspace")

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

def _get_items(table: str, user: dict):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT id, title, description, content, created_at, access_control, user_id FROM {table} ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = []
    for r in rows:
        item_user_id = r[6]
        access_control = r[5] if r[5] else {"type": "public", "allow_public_write": False, "access_list": []}

        has_access = False
        if user.get("role") == "admin":
            has_access = True
        elif item_user_id == user["id"]:
            has_access = True
        elif access_control.get("type") == "public":
            has_access = True
        else:
            access_list = access_control.get("access_list", [])
            user_access_id = f"user-{user['id']}"
            if any(a.get("id") == user_access_id for a in access_list):
                has_access = True
                
        if has_access:
            result.append({
                "id": r[0], 
                "title": r[1], 
                "description": r[2] or "", 
                "content": r[3] or "", 
                "author": "By Admin" if user.get("role") == "admin" or item_user_id != user["id"] else "By You", 
                "updated": "Just now",
                "access_control": access_control,
                "user_id": item_user_id
            })
    return result

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

def _delete_item(table: str, item_id: str, user: dict, label: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT user_id FROM {table} WHERE id = %s", (item_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"{label} not found")
        
    if user.get("role") != "admin" and row[0] != user["id"]:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Permission denied to delete this item")

    cur.execute(f"DELETE FROM {table} WHERE id = %s", (item_id,))
    conn.commit()
    cur.close()
    conn.close()
    if table == "knowledge":
        clear_rag_cache()
    return {"status": "success"}

def _update_item(table: str, item_id: str, item: WorkspaceItemUpdate, user: dict, label: str):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(f"SELECT user_id, access_control FROM {table} WHERE id = %s", (item_id,))
    row = cur.fetchone()
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail=f"{label} not found")
        
    item_user_id = row[0]
    access_control = row[1] if row[1] else {}
    
    can_write = False
    if user.get("role") == "admin":
        can_write = True
    elif item_user_id == user["id"]:
        can_write = True
    elif access_control.get("type") == "public" and access_control.get("allow_public_write") is True:
        can_write = True

    if not can_write:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Permission denied to edit this item")

    ac = json.dumps(item.access_control) if item.access_control else json.dumps({"type": "public", "allow_public_write": False, "access_list": []})
    
    cur.execute(
        f"UPDATE {table} SET title = %s, description = %s, content = %s, access_control = %s WHERE id = %s",
        (item.title, item.description, item.content, ac, item_id)
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
    return _get_items("prompts", current_user)

@router.post("/prompts")
async def create_prompt(item: WorkspaceItemCreate, current_user: dict = Depends(get_current_user)):
    return _upsert_item("prompts", item.id, current_user["id"], item.title, item.description, item.content, item.access_control)

@router.put("/prompts/{item_id}")
async def update_prompt(item_id: str, item: WorkspaceItemUpdate, current_user: dict = Depends(get_current_user)):
    return _update_item("prompts", item_id, item, current_user, "Prompt")

@router.delete("/prompts/{item_id}")
async def delete_prompt(item_id: str, current_user: dict = Depends(get_current_user)):
    return _delete_item("prompts", item_id, current_user, "Prompt")

# ─── Skills ──────────────────────────────────────────────────────────────────

@router.get("/skills")
async def get_skills(current_user: dict = Depends(get_current_user)):
    return _get_items("skills", current_user)

@router.post("/skills")
async def create_skill(item: WorkspaceItemCreate, current_user: dict = Depends(get_current_user)):
    return _upsert_item("skills", item.id, current_user["id"], item.title, item.description, item.content, item.access_control)

@router.put("/skills/{item_id}")
async def update_skill(item_id: str, item: WorkspaceItemUpdate, current_user: dict = Depends(get_current_user)):
    return _update_item("skills", item_id, item, current_user, "Skill")

@router.delete("/skills/{item_id}")
async def delete_skill(item_id: str, current_user: dict = Depends(get_current_user)):
    return _delete_item("skills", item_id, current_user, "Skill")

# ─── Tools ───────────────────────────────────────────────────────────────────

@router.get("/tools")
async def get_tools(current_user: dict = Depends(get_current_user)):
    return _get_items("tools", current_user)

@router.post("/tools")
async def create_tool(item: WorkspaceItemCreate, current_user: dict = Depends(get_current_user)):
    return _upsert_item("tools", item.id, current_user["id"], item.title, item.description, item.content, item.access_control)

@router.put("/tools/{item_id}")
async def update_tool(item_id: str, item: WorkspaceItemUpdate, current_user: dict = Depends(get_current_user)):
    return _update_item("tools", item_id, item, current_user, "Tool")

@router.delete("/tools/{item_id}")
async def delete_tool(item_id: str, current_user: dict = Depends(get_current_user)):
    return _delete_item("tools", item_id, current_user, "Tool")

@router.post("/tools/{item_id}/execute")
async def execute_tool(item_id: str, payload: dict, current_user: dict = Depends(get_current_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, content, access_control FROM tools WHERE id = %s", (item_id,))
    row = cur.fetchone()
    
    if not row:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Tool not found")
        
    item_user_id = row[0]
    code = row[1]
    access_control = row[2] if row[2] else {}
    
    can_execute = False
    if current_user.get("role") == "admin":
        can_execute = True
    elif item_user_id == current_user["id"]:
        can_execute = True
    elif access_control.get("type") == "public":
        can_execute = True
    else:
        user_access_id = f"user-{current_user['id']}"
        access_list = access_control.get("access_list", [])
        if any(a.get("id") == user_access_id for a in access_list):
            can_execute = True
            
    if not can_execute:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Permission denied to execute this tool")
        
    cur.close()
    conn.close()
    
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
            if access_control:
                if isinstance(access_control, dict):
                    ac_data = access_control
                else:
                    import json
                    ac_data = json.loads(access_control)
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
    return _get_items("knowledge", current_user)

@router.post("/knowledge")
async def create_knowledge(item: WorkspaceItemCreate, current_user: dict = Depends(get_current_user)):
    return _upsert_item("knowledge", item.id, current_user["id"], item.title, item.description, item.content, item.access_control)

@router.put("/knowledge/{item_id}")
async def update_knowledge(item_id: str, item: WorkspaceItemUpdate, current_user: dict = Depends(get_current_user)):
    return _update_item("knowledge", item_id, item, current_user, "Knowledge")

@router.delete("/knowledge/{item_id}")
async def delete_knowledge(item_id: str, current_user: dict = Depends(get_current_user)):
    return _delete_item("knowledge", item_id, current_user, "Knowledge")
