from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
import jwt
from database.db import get_conn
from routers.auth import SECRET_KEY, ALGORITHM, pwd_context

router = APIRouter(prefix="/api/users")

def get_current_user(authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_admin_user(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return current_user

class UserCreate(BaseModel):
    name: str
    email: str
    password: str
    role: str = "user"

class UserUpdate(BaseModel):
    name: str
    email: str
    role: str
    password: str = None

@router.post("/me/api-key")
async def generate_api_key(current_user: dict = Depends(get_current_user)):
    import secrets
    api_key = f"sk-vibe-{secrets.token_hex(20)}"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE users SET api_key = %s WHERE id = %s", (api_key, current_user["id"]))
    conn.commit()
    cur.close()
    conn.close()
    # Returned in full only here; store it — regenerating revokes the old one.
    return {"api_key": api_key}


@router.get("/me/api-key")
async def api_key_status(current_user: dict = Depends(get_current_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT api_key FROM users WHERE id = %s", (current_user["id"],))
    row = cur.fetchone()
    cur.close()
    conn.close()
    key = row[0] if row else None
    return {"hasKey": bool(key), "preview": f"{key[:11]}…{key[-4:]}" if key else None}


@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, email, role, status FROM users WHERE id = %s", (current_user["id"],))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return {"id": row[0], "name": row[1], "email": row[2], "role": row[3], "status": row[4]}

@router.get("/")
async def get_users(admin: dict = Depends(get_admin_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, email, role, status FROM users")
    users = [
        {"id": r[0], "name": r[1], "email": r[2], "role": r[3], "status": r[4]}
        for r in cur.fetchall()
    ]
    cur.close()
    conn.close()
    return users

@router.post("/")
async def create_user(user: UserCreate, admin: dict = Depends(get_admin_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE email = %s", (user.email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")
        
    hashed_password = pwd_context.hash(user.password)
    cur.execute(
        "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, %s) RETURNING id",
        (user.name, user.email, hashed_password, user.role)
    )
    user_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return {"id": user_id, "name": user.name, "email": user.email, "role": user.role}

@router.delete("/{user_id}")
async def delete_user(user_id: int, admin: dict = Depends(get_admin_user)):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
    conn.commit()
    cur.close()
    conn.close()
    return {"message": "User deleted"}

@router.put("/{user_id}")
async def update_user(user_id: int, user: UserUpdate, admin: dict = Depends(get_admin_user)):
    conn = get_conn()
    cur = conn.cursor()
    
    # Check if user exists
    cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
    if not cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=404, detail="User not found")
        
    # Check email duplicate (if email changed)
    cur.execute("SELECT id FROM users WHERE email = %s AND id != %s", (user.email, user_id))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Email already in use")
        
    if user.password:
        hashed_password = pwd_context.hash(user.password)
        cur.execute(
            "UPDATE users SET name = %s, email = %s, role = %s, password = %s WHERE id = %s",
            (user.name, user.email, user.role.lower(), hashed_password, user_id)
        )
    else:
        cur.execute(
            "UPDATE users SET name = %s, email = %s, role = %s WHERE id = %s",
            (user.name, user.email, user.role.lower(), user_id)
        )
        
    conn.commit()
    cur.close()
    conn.close()
    return {"id": user_id, "name": user.name, "email": user.email, "role": user.role}
