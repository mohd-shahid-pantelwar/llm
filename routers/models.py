from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import os
import requests
import time
import json
from database.db import get_conn
from routers.users import get_current_user, get_admin_user

router = APIRouter(prefix="/api")

class PresetData(BaseModel):
    id: Optional[str] = None
    name: str
    provider: str
    description: Optional[str] = None
    systemPrompt: Optional[str] = None
    capabilities: Optional[dict] = None
    defaultFeatures: Optional[dict] = None
    builtinTools: Optional[dict] = None
    access_control: Optional[dict] = None
    selectedKnowledge: Optional[list] = None
    selectedTools: Optional[list] = None
    selectedSkills: Optional[list] = None

@router.get("/models")
def get_models(current_user: dict = Depends(get_current_user)):
    mapped_models = []
    seen_ids = set()
    
    # 1. Fetch from local DB
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, name, meta, is_active, access_control, user_id FROM models")
        db_models = cur.fetchall()
        for row in db_models:
            meta = row[2] if row[2] else {}
            ac = row[4] if row[4] else {"type": "public", "allow_public_write": False, "access_list": []}
            owner_id = row[5]
            is_active = row[3]
            
            # Check access permission
            is_visible = False
            # Admin always sees everything
            if current_user.get("role") == "admin":
                is_visible = True
            else:
                # Standard users only see active models they have access to
                if is_active:
                    if owner_id == current_user.get("id"):
                        is_visible = True
                    elif ac.get("type", "public") == "public":
                        is_visible = True
                    elif ac.get("type") == "private":
                        access_list = ac.get("access_list", [])
                        for entry in access_list:
                            if entry.get("type") == "user" and int(entry.get("id")) == int(current_user.get("id")):
                                is_visible = True
                                break
            
            if is_visible:
                mapped_models.append({
                    "id": row[0],
                    "name": row[1],
                    "provider": meta.get("provider", "Custom"),
                    "description": meta.get("description", "A custom model"),
                    "systemPrompt": meta.get("systemPrompt", ""),
                    "capabilities": meta.get("capabilities", {}),
                    "defaultFeatures": meta.get("defaultFeatures", {}),
                    "builtinTools": meta.get("builtinTools", {}),
                    "selectedKnowledge": meta.get("selectedKnowledge", []),
                    "selectedTools": meta.get("selectedTools", []),
                    "selectedSkills": meta.get("selectedSkills", []),
                    "color": "from-orange-500 to-amber-600",
                    "is_active": is_active,
                    "access_control": ac
                })
                seen_ids.add(row[0])
        cur.close()
        conn.close()
    except Exception as e:
        print("Error fetching from DB:", e)
        
    # 2. Fetch from Ollama (Admin Only)
    if current_user.get("role") == "admin":
        try:
            OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
            res = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
            if res.status_code == 200:
                data = res.json()
                for m in data.get("models", []):
                    name = m.get("name", "")
                    if "embed" in name.lower():
                        continue
                    model_id = m.get("model", m.get("name"))
                    if model_id in seen_ids:
                        continue
                        
                    mapped_models.append({
                        "id": model_id,
                        "name": m.get("name", "").split(":")[0].capitalize(),
                        "provider": "Ollama Local",
                        "description": f"Local Ollama model: {m.get('model')}",
                        "systemPrompt": "",
                        "color": "from-blue-500 to-indigo-600",
                        "is_active": True,
                        "access_control": {"type": "public", "allow_public_write": False, "access_list": []}
                    })
        except Exception as e:
            print("Error fetching from Ollama:", e)
        
    return mapped_models

@router.post("/models/preset")
def create_model_preset(preset: PresetData, current_user: dict = Depends(get_admin_user)):
    user_id = current_user.get("id")
    try:
        model_id = preset.id
        if not model_id:
            model_id = preset.name.lower().replace(" ", "-")
            
        meta = json.dumps({
            "description": preset.description,
            "provider": preset.provider,
            "systemPrompt": preset.systemPrompt,
            "capabilities": preset.capabilities,
            "defaultFeatures": preset.defaultFeatures,
            "builtinTools": preset.builtinTools,
            "selectedKnowledge": preset.selectedKnowledge,
            "selectedTools": preset.selectedTools,
            "selectedSkills": preset.selectedSkills
        })
        
        ac = json.dumps(preset.access_control) if preset.access_control else json.dumps({"type": "public", "allow_public_write": False, "access_list": []})
        now = int(time.time())
        
        conn = get_conn()
        cur = conn.cursor()
        
        # Check if the model already exists globally
        cur.execute("SELECT user_id FROM models WHERE id = %s", (model_id,))
        row = cur.fetchone()
        if row:
            existing_user_id = row[0]
            # If the model has no owner or belongs to this user, allow updating it
            if existing_user_id is None or existing_user_id == user_id:
                cur.execute("""
                    UPDATE models 
                    SET name = %s, meta = %s, updated_at = %s, user_id = %s, access_control = %s 
                    WHERE id = %s
                """, (preset.name, meta, now, user_id, ac, model_id))
            else:
                cur.close()
                conn.close()
                raise HTTPException(status_code=403, detail="A model preset with this ID already exists and is owned by another user.")
        else:
            cur.execute("""
                INSERT INTO models (id, user_id, name, meta, updated_at, created_at, is_active, access_control)
                VALUES (%s, %s, %s, %s, %s, %s, true, %s)
            """, (model_id, user_id, preset.name, meta, now, now, ac))
            
        conn.commit()
        cur.close()
        conn.close()
        
        return {"status": "success", "id": model_id}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/models/preset/{model_id}")
def delete_model_preset(model_id: str, current_user: dict = Depends(get_admin_user)):
    user_id = current_user.get("id")
    try:
        conn = get_conn()
        cur = conn.cursor()
        # Only delete models owned by this user or with no owner
        cur.execute("DELETE FROM models WHERE id = %s AND (user_id = %s OR user_id IS NULL)", (model_id, user_id))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.patch("/models/preset/{model_id}/toggle")
def toggle_model_active(model_id: str, current_user: dict = Depends(get_admin_user)):
    """Toggle is_active for a model preset and persist to DB."""
    user_id = current_user.get("id")
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT is_active, user_id FROM models WHERE id = %s", (model_id,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            raise HTTPException(status_code=404, detail="Model not found")
        
        is_active, existing_user_id = row[0], row[1]
        if existing_user_id is not None and existing_user_id != user_id:
            cur.close()
            conn.close()
            raise HTTPException(status_code=403, detail="Not authorized to modify this model preset")

        new_active = not is_active
        cur.execute(
            "UPDATE models SET is_active = %s, updated_at = %s WHERE id = %s",
            (new_active, int(time.time()), model_id)
        )
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success", "is_active": new_active}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))