from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import requests
import time
import json
from database.db import get_conn

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

@router.get("/models")
def get_models():
    mapped_models = []
    
    # 1. Fetch from local DB
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, name, meta, is_active FROM models")
        db_models = cur.fetchall()
        for row in db_models:
            meta = row[2] if row[2] else {}
            mapped_models.append({
                "id": row[0],
                "name": row[1],
                "provider": meta.get("provider", "Custom"),
                "description": meta.get("description", "A custom model"),
                "systemPrompt": meta.get("systemPrompt", ""),
                "capabilities": meta.get("capabilities", {}),
                "defaultFeatures": meta.get("defaultFeatures", {}),
                "builtinTools": meta.get("builtinTools", {}),
                "color": "from-orange-500 to-amber-600",
                "is_active": row[3]
            })
        cur.close()
        conn.close()
    except Exception as e:
        print("Error fetching from DB:", e)
        
    # 2. Fetch from Ollama
    try:
        res = requests.get("http://10.0.10.131:11434/api/tags")
        if res.status_code == 200:
            data = res.json()
            for m in data.get("models", []):
                name = m.get("name", "")
                if "embed" in name.lower():
                    continue
                mapped_models.append({
                    "id": m.get("model", m.get("name")),
                    "name": m.get("name", "").split(":")[0].capitalize(),
                    "provider": "Ollama Local",
                    "description": f"Local Ollama model: {m.get('model')}",
                    "systemPrompt": "",
                    "color": "from-blue-500 to-indigo-600",
                    "is_active": True
                })
    except Exception as e:
        print("Error fetching from Ollama:", e)
        
    return mapped_models

@router.post("/models/preset")
def create_model_preset(preset: PresetData):
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
            "builtinTools": preset.builtinTools
        })
        
        now = int(time.time())
        
        conn = get_conn()
        cur = conn.cursor()
        
        # Check if exists
        cur.execute("SELECT id FROM models WHERE id = %s", (model_id,))
        if cur.fetchone():
            cur.execute("""
                UPDATE models 
                SET name = %s, meta = %s, updated_at = %s 
                WHERE id = %s
            """, (preset.name, meta, now, model_id))
        else:
            cur.execute("""
                INSERT INTO models (id, name, meta, updated_at, created_at, is_active)
                VALUES (%s, %s, %s, %s, %s, true)
            """, (model_id, preset.name, meta, now, now))
            
        conn.commit()
        cur.close()
        conn.close()
        
        return {"status": "success", "id": model_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.delete("/models/preset/{model_id}")
def delete_model_preset(model_id: str):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM models WHERE id = %s", (model_id,))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))