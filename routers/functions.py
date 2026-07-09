"""Custom functions = pipeline filters that intercept chat requests/responses.

A function is user-authored Python defining a `Filter` class with optional
`inlet(body)` (runs before the LLM, can rewrite the query/system prompt) and
`outlet(body)` (runs after, can rewrite the answer). Only admins can create or
edit them, since the code executes on the server.

NOTE: exec() of user code is inherently privileged. This mirrors the existing
workspace Tools design (same trust model) — admin-only, server-side. It is NOT
a hardened sandbox; treat function authors as trusted operators.
"""

import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from database.db import get_conn
from routers.users import get_current_user, get_admin_user

router = APIRouter(prefix="/api/functions")

EXAMPLE = '''"""
Example filter. inlet() runs before the model, outlet() runs after.
`body` has: query, system_prompt, answer (outlet only), user.
Return the modified body.
"""

class Filter:
    def inlet(self, body):
        # e.g. force a house style
        # body["system_prompt"] = (body.get("system_prompt") or "") + "\\nAlways answer in British English."
        return body

    def outlet(self, body):
        # e.g. redact something from the answer
        # body["answer"] = body["answer"].replace("secret", "[redacted]")
        return body
'''


class FunctionCreate(BaseModel):
    name: str
    description: str = ""
    content: str = ""
    kind: str = "filter"


class FunctionUpdate(BaseModel):
    name: str
    description: str = ""
    content: str = ""
    is_active: Optional[bool] = None


def _row_to_dict(r):
    return {
        "id": r[0], "name": r[2], "description": r[3], "kind": r[4],
        "content": r[5], "is_active": r[6],
        "created_at": r[7].isoformat() if r[7] else None,
    }


@router.get("")
async def list_functions(current_user: dict = Depends(get_current_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, name, description, kind, content, is_active, created_at FROM functions ORDER BY created_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return [_row_to_dict(r) for r in rows]


@router.get("/example")
async def function_example(admin: dict = Depends(get_admin_user)):
    return {"content": EXAMPLE}


@router.post("")
async def create_function(fn: FunctionCreate, admin: dict = Depends(get_admin_user)):
    if not fn.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    _validate_code(fn.content)
    fid = f"func-{uuid.uuid4().hex[:12]}"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO functions (id, user_id, name, description, kind, content, is_active, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, TRUE, NOW()) RETURNING id, user_id, name, description, kind, content, is_active, created_at",
        (fid, admin.get("id"), fn.name, fn.description, fn.kind, fn.content),
    )
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    return _row_to_dict(row)


@router.put("/{function_id}")
async def update_function(function_id: str, fn: FunctionUpdate, admin: dict = Depends(get_admin_user)):
    _validate_code(fn.content)
    conn = get_conn()
    cur = conn.cursor()
    if fn.is_active is None:
        cur.execute(
            "UPDATE functions SET name=%s, description=%s, content=%s WHERE id=%s RETURNING id",
            (fn.name, fn.description, fn.content, function_id),
        )
    else:
        cur.execute(
            "UPDATE functions SET name=%s, description=%s, content=%s, is_active=%s WHERE id=%s RETURNING id",
            (fn.name, fn.description, fn.content, fn.is_active, function_id),
        )
    updated = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    if not updated:
        raise HTTPException(status_code=404, detail="Function not found")
    return {"status": "updated"}


@router.patch("/{function_id}/toggle")
async def toggle_function(function_id: str, admin: dict = Depends(get_admin_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE functions SET is_active = NOT is_active WHERE id=%s RETURNING is_active", (function_id,))
    row = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Function not found")
    return {"is_active": row[0]}


@router.delete("/{function_id}")
async def delete_function(function_id: str, admin: dict = Depends(get_admin_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM functions WHERE id=%s RETURNING id", (function_id,))
    deleted = cur.fetchone()
    conn.commit()
    cur.close()
    conn.close()
    if not deleted:
        raise HTTPException(status_code=404, detail="Function not found")
    return {"status": "deleted"}


def _validate_code(code: str):
    if not code or not code.strip():
        return
    try:
        compile(code, "<function>", "exec")
    except SyntaxError as e:
        raise HTTPException(status_code=400, detail=f"Python syntax error: {e}")


# ─── Execution helpers used by the chat pipeline ───────────────────────────────

def _load_active_filters():
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, name, content FROM functions WHERE is_active = TRUE AND kind = 'filter' ORDER BY created_at")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return rows
    except Exception as e:
        print(f"[Functions] load failed: {e}")
        return []


def _run_stage(stage: str, body: dict) -> dict:
    """Run every active filter's inlet/outlet. A failing filter is skipped,
    never breaks the chat."""
    for fid, name, content in _load_active_filters():
        if not content or not content.strip():
            continue
        try:
            env = {}
            exec(content, env, env)
            Filter = env.get("Filter")
            if not Filter:
                continue
            instance = Filter()
            method = getattr(instance, stage, None)
            if not callable(method):
                continue
            result = method(dict(body))
            if isinstance(result, dict):
                body = result
        except Exception as e:
            print(f"[Functions] filter '{name}' {stage}() error: {e}")
    return body


def apply_inlet(query: str, system_prompt, user_id):
    body = _run_stage("inlet", {"query": query, "system_prompt": system_prompt, "user": user_id})
    return body.get("query", query), body.get("system_prompt", system_prompt)


def apply_outlet(answer: str, query: str, user_id):
    body = _run_stage("outlet", {"answer": answer, "query": query, "user": user_id})
    return body.get("answer", answer)
