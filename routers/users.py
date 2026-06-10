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
