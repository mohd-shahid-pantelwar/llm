from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from passlib.context import CryptContext
import jwt
import datetime
import os
from database.db import get_conn

router = APIRouter(prefix="/api")

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = os.getenv("WEBUI_SECRET_KEY", "my_super_secret_key_for_openwebui")
ALGORITHM = "HS256"

# Configuration flag matching open_webui design
ENABLE_SIGNUP = False

class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str

@router.get("/status")
async def get_auth_status():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return {"has_users": count > 0}

@router.post("/login")
async def login(req: LoginRequest):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id, name, email, password, role FROM users WHERE email = %s", (req.email,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if not user or not pwd_context.verify(req.password, user[3]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token_data = {
        "sub": user[2],
        "id": user[0],
        "name": user[1],
        "role": user[4],
        "exp": datetime.datetime.utcnow() + datetime.timedelta(days=7)
    }
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
    
    return {
        "token": token,
        "user": {
            "id": user[0],
            "name": user[1],
            "email": user[2],
            "role": user[4]
        }
    }

@router.post("/register")
async def register(req: RegisterRequest):
    conn = get_conn()
    cur = conn.cursor()
    
    # Mirroring open_webui/routers/auths.py signup logic
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    has_users = count > 0
    
    if has_users and not ENABLE_SIGNUP:
        cur.close()
        conn.close()
        raise HTTPException(status_code=403, detail="Public registration is disabled")
        
    # Check if user exists
    cur.execute("SELECT id FROM users WHERE email = %s", (req.email,))
    if cur.fetchone():
        cur.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")
    
    role = "admin" if count == 0 else "user"
    
    password_bytes = req.password.encode('utf-8')
    if len(password_bytes) > 72:
        password_bytes = password_bytes[:72]
        req.password = password_bytes.decode('utf-8', errors='ignore')
        
    hashed_password = pwd_context.hash(req.password)
    cur.execute(
        "INSERT INTO users (name, email, password, role) VALUES (%s, %s, %s, %s) RETURNING id",
        (req.name, req.email, hashed_password, role)
    )
    user_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    
    return {"message": "User registered successfully", "user_id": user_id}
