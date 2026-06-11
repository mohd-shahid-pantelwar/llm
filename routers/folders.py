from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional, List
import time
from database.db import get_conn
from routers.users import get_current_user

router = APIRouter(prefix="/api/folders")

class FolderCreate(BaseModel):
    id: str
    name: str
    background_image: Optional[str] = ""
    system_prompt: Optional[str] = ""
    knowledge: Optional[str] = ""

class FolderUpdate(BaseModel):
    name: str

@router.get("")
async def get_folders(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    
    # 1. Fetch folders
    cur.execute(
        """
        SELECT id, name, background_image, system_prompt, knowledge
        FROM folders
        WHERE user_id = %s
        ORDER BY created_at ASC
        """,
        (user_id,)
    )
    folder_rows = cur.fetchall()
    
    folders_dict = {}
    for r in folder_rows:
        folders_dict[r[0]] = {
            "id": r[0],
            "name": r[1],
            "backgroundImage": r[2],
            "systemPrompt": r[3],
            "knowledge": r[4],
            "threadIds": []
        }
        
    # 2. Fetch thread associations
    cur.execute(
        """
        SELECT id, folder_id
        FROM chats
        WHERE user_id = %s AND folder_id IS NOT NULL AND is_archived = false
        """,
        (user_id,)
    )
    chat_rows = cur.fetchall()
    cur.close()
    conn.close()
    
    for r in chat_rows:
        chat_id, folder_id = r[0], r[1]
        if folder_id in folders_dict:
            folders_dict[folder_id]["threadIds"].append(chat_id)
            
    return list(folders_dict.values())

@router.post("")
async def create_folder(folder: FolderCreate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    
    # Check if folder exists
    cur.execute("SELECT id FROM folders WHERE id = %s AND user_id = %s", (folder.id, user_id))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Folder already exists")
        
    now = int(time.time())
    cur.execute(
        """
        INSERT INTO folders (id, user_id, name, background_image, system_prompt, knowledge, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            folder.id,
            user_id,
            folder.name,
            folder.background_image,
            folder.system_prompt,
            folder.knowledge,
            now
        )
    )
    
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "id": folder.id}

@router.delete("/{folder_id}")
async def delete_folder(folder_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    
    # Check folder ownership
    cur.execute("SELECT id FROM folders WHERE id = %s AND user_id = %s", (folder_id, user_id))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Folder not found")
        
    cur.execute("DELETE FROM folders WHERE id = %s AND user_id = %s", (folder_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success"}

@router.put("/{folder_id}")
async def update_folder(folder_id: str, folder: FolderUpdate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("SELECT id FROM folders WHERE id = %s AND user_id = %s", (folder_id, user_id))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Folder not found")
        
    cur.execute("UPDATE folders SET name = %s WHERE id = %s AND user_id = %s", (folder.name, folder_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success"}
