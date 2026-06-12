from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import time
import datetime
import uuid
import json
from database.db import get_conn
from routers.users import get_current_user

router = APIRouter(prefix="/api/notes")

class NoteCreate(BaseModel):
    id: Optional[str] = None
    title: str
    content: str = ""
    color: str = "from-amber-500 to-orange-500"
    chat_history: list = []

class NoteUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    color: Optional[str] = None
    chat_history: Optional[list] = None

def format_relative_time(timestamp: int) -> str:
    if not timestamp:
        return "Just now"
    dt = datetime.datetime.fromtimestamp(timestamp)
    now = datetime.datetime.now()
    diff = int(time.time()) - timestamp
    if diff < 60:
        return "Just now"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    days = (now.date() - dt.date()).days
    if days == 1:
        return "Yesterday"
    return f"{days}d ago"

@router.get("")
async def get_notes(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, title, content, color, chat_history, updated_at
        FROM notes
        WHERE user_id = %s
        ORDER BY updated_at DESC
        """,
        (user_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "id": r[0],
            "title": r[1],
            "content": r[2],
            "color": r[3],
            "chatHistory": r[4] if r[4] is not None else [],
            "updatedAt": format_relative_time(r[5])
        }
        for r in rows
    ]

@router.post("")
async def create_note(note: NoteCreate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    
    now = int(time.time())
    note_id = note.id or f"note-{uuid.uuid4()}"
    
    cur.execute(
        """
        INSERT INTO notes (id, user_id, title, content, color, chat_history, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (note_id, user_id, note.title, note.content, note.color, json.dumps(note.chat_history), now, now)
    )
    conn.commit()
    cur.close()
    conn.close()
    
    return {"status": "success", "id": note_id, "updatedAt": "Just now"}

@router.put("/{note_id}")
async def update_note(note_id: str, note: NoteUpdate, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    
    fields = []
    params = []
    
    if note.title is not None:
        fields.append("title = %s")
        params.append(note.title)
    if note.content is not None:
        fields.append("content = %s")
        params.append(note.content)
    if note.color is not None:
        fields.append("color = %s")
        params.append(note.color)
    if note.chat_history is not None:
        fields.append("chat_history = %s")
        params.append(json.dumps(note.chat_history))
        
    if not fields:
        return {"status": "no changes"}
        
    now = int(time.time())
    fields.append("updated_at = %s")
    params.append(now)
    
    params.extend([note_id, user_id])
    
    cur.execute(
        f"UPDATE notes SET {', '.join(fields)} WHERE id = %s AND user_id = %s",
        tuple(params)
    )
    conn.commit()
    cur.close()
    conn.close()
    
    return {"status": "success", "updatedAt": "Just now"}

@router.delete("/{note_id}")
async def delete_note(note_id: str, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    
    cur.execute("DELETE FROM notes WHERE id = %s AND user_id = %s RETURNING id", (note_id, user_id))
    deleted = cur.fetchone()
    
    conn.commit()
    cur.close()
    conn.close()
    
    if not deleted:
        raise HTTPException(status_code=404, detail="Note not found")
        
    return {"status": "success"}
