from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import json
import time
import datetime
from database.db import get_conn
from routers.users import get_current_user

router = APIRouter(prefix="/api/feedback")


class FeedbackCreate(BaseModel):
    message_id: str
    chat_id: Optional[str] = None
    model_name: Optional[str] = None
    type: str                          # "like" | "dislike"
    rating: Optional[int] = None
    reasons: List[str] = []
    details: Optional[str] = None
    tag: Optional[str] = None


class FeedbackUpdate(BaseModel):
    rating: Optional[int] = None
    reasons: Optional[List[str]] = None
    details: Optional[str] = None
    tag: Optional[str] = None


def format_relative_time(timestamp: int) -> str:
    if not timestamp:
        return "Just now"
    dt = datetime.datetime.fromtimestamp(timestamp)
    now = datetime.datetime.now()
    diff = int(time.time()) - timestamp
    if diff < 60:
        return "a few seconds ago"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    days = (now.date() - dt.date()).days
    return f"{days}d ago"


# ─── Save feedback ────────────────────────────────────────────────────────────

@router.post("")
async def create_feedback(
    fb: FeedbackCreate,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user.get("id")
    if fb.type not in ("like", "dislike"):
        raise HTTPException(status_code=400, detail="type must be 'like' or 'dislike'")
    if fb.rating is not None and not (1 <= fb.rating <= 10):
        raise HTTPException(status_code=400, detail="rating must be between 1 and 10")

    conn = get_conn()
    cur = conn.cursor()
    now = int(time.time())

    # Upsert: one feedback entry per (user_id, message_id)
    cur.execute(
        """
        INSERT INTO feedback
            (user_id, message_id, chat_id, model_name, type, rating, reasons, details, tag, created_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        RETURNING id
        """,
        (
            user_id,
            fb.message_id,
            fb.chat_id,
            fb.model_name,
            fb.type,
            fb.rating,
            json.dumps(fb.reasons),
            fb.details,
            fb.tag,
            now,
        )
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    if not row:
        # Already existed — do an update instead
        return await update_feedback_by_message(fb.message_id, FeedbackUpdate(
            rating=fb.rating, reasons=fb.reasons, details=fb.details, tag=fb.tag
        ), current_user)

    return {"status": "success", "id": row[0]}


# ─── Model leaderboard from collected feedback (admin) ────────────────────────

@router.get("/leaderboard")
async def feedback_leaderboard(current_user: dict = Depends(get_current_user)):
    if current_user.get("role", "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin only")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT
            COALESCE(model_name, 'unknown') AS model,
            COUNT(*) FILTER (WHERE type = 'like') AS likes,
            COUNT(*) FILTER (WHERE type = 'dislike') AS dislikes,
            AVG(rating) FILTER (WHERE rating IS NOT NULL) AS avg_rating,
            COUNT(*) AS total
        FROM feedback
        GROUP BY COALESCE(model_name, 'unknown')
        ORDER BY COUNT(*) DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()

    leaderboard = []
    for model, likes, dislikes, avg_rating, total in rows:
        rated = likes + dislikes
        leaderboard.append({
            "model": model,
            "likes": likes,
            "dislikes": dislikes,
            "total": total,
            "avgRating": round(float(avg_rating), 2) if avg_rating is not None else None,
            "winRate": round(likes / rated, 3) if rated else None,
        })
    leaderboard.sort(key=lambda x: (x["winRate"] is not None, x["winRate"] or 0, x["total"]), reverse=True)
    return leaderboard


# ─── List all feedback (admin) ─────────────────────────────────────────────────

@router.get("")
async def get_all_feedback(current_user: dict = Depends(get_current_user)):
    if current_user.get("role", "").upper() != "ADMIN":
        raise HTTPException(status_code=403, detail="Admin only")

    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT f.id, f.message_id, f.chat_id, f.model_name, f.type,
               f.rating, f.reasons, f.details, f.tag, f.created_at,
               u.name, u.email
        FROM feedback f
        LEFT JOIN users u ON u.id = f.user_id
        ORDER BY f.created_at DESC
        """
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    result = []
    for r in rows:
        result.append({
            "id": r[0],
            "messageId": r[1],
            "chatId": r[2],
            "modelName": r[3],
            "type": r[4],
            "rating": r[5],
            "reasons": r[6] if isinstance(r[6], list) else json.loads(r[6]) if r[6] else [],
            "details": r[7],
            "tag": r[8],
            "createdAt": format_relative_time(r[9]),
            "userName": r[10],
            "userEmail": r[11],
            "result": "WON" if r[4] == "like" else "LOST",
        })
    return result


# ─── My feedback ──────────────────────────────────────────────────────────────

@router.get("/mine")
async def get_my_feedback(current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, message_id, chat_id, model_name, type, rating, reasons, details, tag, created_at
        FROM feedback
        WHERE user_id = %s
        ORDER BY created_at DESC
        """,
        (user_id,)
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    return [
        {
            "id": r[0],
            "messageId": r[1],
            "chatId": r[2],
            "modelName": r[3],
            "type": r[4],
            "rating": r[5],
            "reasons": r[6] if isinstance(r[6], list) else json.loads(r[6]) if r[6] else [],
            "details": r[7],
            "tag": r[8],
            "createdAt": format_relative_time(r[9]),
            "result": "WON" if r[4] == "like" else "LOST",
        }
        for r in rows
    ]


# ─── Update feedback by message_id ────────────────────────────────────────────

@router.put("/message/{message_id}")
async def update_feedback_by_message(
    message_id: str,
    fb: FeedbackUpdate,
    current_user: dict = Depends(get_current_user)
):
    user_id = current_user.get("id")
    conn = get_conn()
    cur = conn.cursor()

    fields = []
    params = []
    if fb.rating is not None:
        fields.append("rating = %s"); params.append(fb.rating)
    if fb.reasons is not None:
        fields.append("reasons = %s"); params.append(json.dumps(fb.reasons))
    if fb.details is not None:
        fields.append("details = %s"); params.append(fb.details)
    if fb.tag is not None:
        fields.append("tag = %s"); params.append(fb.tag)

    if not fields:
        return {"status": "no changes"}

    params += [message_id, user_id]
    cur.execute(
        f"UPDATE feedback SET {', '.join(fields)} WHERE message_id = %s AND user_id = %s",
        tuple(params)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"status": "success"}


# ─── Delete feedback ───────────────────────────────────────────────────────────

@router.delete("/{feedback_id}")
async def delete_feedback(feedback_id: int, current_user: dict = Depends(get_current_user)):
    user_id = current_user.get("id")
    is_admin = current_user.get("role", "").upper() == "ADMIN"

    conn = get_conn()
    cur = conn.cursor()

    if is_admin:
        cur.execute("DELETE FROM feedback WHERE id = %s RETURNING id", (feedback_id,))
    else:
        cur.execute(
            "DELETE FROM feedback WHERE id = %s AND user_id = %s RETURNING id",
            (feedback_id, user_id)
        )

    deleted = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()

    if not deleted:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return {"status": "success"}
