from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from database.db import get_conn
from routers.users import get_current_user

router = APIRouter(prefix="/api/memories")

MAX_MEMORY_CHARS = 500
MAX_MEMORIES_PER_USER = 100


class MemoryCreate(BaseModel):
    content: str


@router.get("")
async def list_memories(current_user: dict = Depends(get_current_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, content, created_at FROM user_memories WHERE user_id = %s ORDER BY created_at DESC",
        (current_user["id"],),
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [{"id": r[0], "content": r[1], "created_at": r[2].isoformat() if r[2] else None} for r in rows]


@router.post("")
async def create_memory(req: MemoryCreate, current_user: dict = Depends(get_current_user)):
    content = req.content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Memory content is required")
    if len(content) > MAX_MEMORY_CHARS:
        raise HTTPException(status_code=400, detail=f"Memory too long (max {MAX_MEMORY_CHARS} chars)")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM user_memories WHERE user_id = %s", (current_user["id"],))
    if cur.fetchone()[0] >= MAX_MEMORIES_PER_USER:
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail=f"Memory limit reached ({MAX_MEMORIES_PER_USER})")
    cur.execute(
        "INSERT INTO user_memories (user_id, content) VALUES (%s, %s) RETURNING id, created_at",
        (current_user["id"], content),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return {"id": row[0], "content": content, "created_at": row[1].isoformat() if row[1] else None}


@router.delete("/{memory_id}")
async def delete_memory(memory_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM user_memories WHERE id = %s AND user_id = %s RETURNING id",
        (memory_id, current_user["id"]),
    )
    deleted = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"status": "deleted"}


def get_user_memory_context(user_id, max_chars: int = 2000):
    """Concatenated memories for prompt injection; empty string if none."""
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            "SELECT content FROM user_memories WHERE user_id = %s ORDER BY created_at DESC",
            (user_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[Memories] fetch failed: {e}")
        return ""
    if not rows:
        return ""
    lines, total = [], 0
    for (content,) in rows:
        if total + len(content) > max_chars:
            break
        lines.append(f"- {content}")
        total += len(content)
    return "Known facts about this user (use when relevant, don't recite):\n" + "\n".join(lines)
