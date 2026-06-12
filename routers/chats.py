from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import json
import time
import datetime
from database.db import get_conn
from routers.users import get_current_user

router = APIRouter(prefix="/api/chats")

class ChatCreate(BaseModel):
    id: str
    title: str
    model_id: str
    messages: List[dict] = []
    pinned: bool = False
    folder_id: Optional[str] = None

class ChatUpdate(BaseModel):
    title: Optional[str] = None
    messages: Optional[List[dict]] = None
    model_id: Optional[str] = None
    pinned: Optional[bool] = None
    is_archived: Optional[bool] = None
    folder_id: Optional[str] = None

def format_relative_time(timestamp: int) -> str:
    if not timestamp:
        return "Just now"
    dt = datetime.datetime.fromtimestamp(timestamp)
    now = datetime.datetime.now()
    
    if dt.date() == now.date():
        diff = int(time.time()) - timestamp
        if diff < 60:
            return "Just now"
        if diff < 3600:
            mins = diff // 60
            return f"{mins}m ago"
        hours = diff // 3600
        return f"{hours}h ago"
    
    date_diff = (now.date() - dt.date()).days
    days_to_show = date_diff + 1
    return f"{days_to_show}d"

@router.get("")
async def get_chats(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, model_id, messages, pinned, folder_id, updated_at, created_at
        FROM chats
        WHERE user_id = %s AND is_archived = false
        ORDER BY updated_at DESC
        """,
        (user_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    chats = []
    for r in rows:
        chats.append({
            "id": r[0],
            "title": r[1],
            "modelId": r[2],
            "messages": r[3] if isinstance(r[3], list) else json.loads(r[3]) if r[3] else [],
            "pinned": r[4],
            "folderId": r[5],
            "lastMessageAt": format_relative_time(r[6])
        })
    return chats

@router.get("/archived")
async def get_archived_chats(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, model_id, messages, pinned, folder_id, updated_at, created_at
        FROM chats
        WHERE user_id = %s AND is_archived = true
        ORDER BY updated_at DESC
        """,
        (user_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    chats = []
    for r in rows:
        chats.append({
            "id": r[0],
            "title": r[1],
            "modelId": r[2],
            "messages": r[3] if isinstance(r[3], list) else json.loads(r[3]) if r[3] else [],
            "pinned": r[4],
            "folderId": r[5],
            "lastMessageAt": "Archived"
        })
    return chats

@router.post("")
async def create_chat(chat: ChatCreate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    
    now = int(time.time())
    
    # Check if chat already exists
    cur.execute("SELECT id FROM chats WHERE id = %s AND user_id = %s", (chat.id, user_id))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Chat already exists")
        
    cur.execute(
        """
        INSERT INTO chats (id, user_id, title, model_id, messages, pinned, folder_id, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            chat.id,
            user_id,
            chat.title,
            chat.model_id,
            json.dumps(chat.messages),
            chat.pinned,
            chat.folder_id,
            now,
            now
        )
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success", "id": chat.id}

@router.put("/{chat_id}")
async def update_chat(chat_id: str, chat: ChatUpdate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("SELECT id FROM chats WHERE id = %s AND user_id = %s", (chat_id, user_id))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Chat not found")
        
    update_fields = []
    params = []
    
    if chat.title is not None:
        update_fields.append("title = %s")
        params.append(chat.title)
    if chat.messages is not None:
        update_fields.append("messages = %s")
        params.append(json.dumps(chat.messages))
    if chat.model_id is not None:
        update_fields.append("model_id = %s")
        params.append(chat.model_id)
    if chat.pinned is not None:
        update_fields.append("pinned = %s")
        params.append(chat.pinned)
    if chat.is_archived is not None:
        update_fields.append("is_archived = %s")
        params.append(chat.is_archived)
    if chat.folder_id is not None:
        # allow setting to null or a folder id
        update_fields.append("folder_id = %s")
        params.append(chat.folder_id if chat.folder_id != "" else None)
        
    if not update_fields:
        cur.close()
        conn.close()
        return {"status": "no changes"}
        
    # Always update updated_at timestamp
    now = int(time.time())
    update_fields.append("updated_at = %s")
    params.append(now)
    
    # Append chat_id and user_id for the WHERE clause
    params.append(chat_id)
    params.append(user_id)
    
    query = f"UPDATE chats SET {', '.join(update_fields)} WHERE id = %s AND user_id = %s"
    cur.execute(query, tuple(params))
    
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success"}

@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("DELETE FROM chats WHERE id = %s AND user_id = %s RETURNING id", (chat_id, user_id))
    deleted = cur.fetchone()
    
    if not deleted:
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="Chat not found")
        
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success"}

@router.delete("")
async def delete_all_chats(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("DELETE FROM chats WHERE user_id = %s", (user_id,))
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success"}
