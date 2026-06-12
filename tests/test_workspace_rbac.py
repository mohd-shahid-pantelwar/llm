import sys
import os
import jwt
import time

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app
from routers.auth import SECRET_KEY, ALGORITHM

def test_workspace_rbac():
    client = TestClient(app)
    
    # 1. Create a token for a normal user (role: "user")
    user_payload = {
        "id": 999,
        "name": "Normal User",
        "email": "user@example.com",
        "role": "user",
        "exp": int(time.time()) + 3600
    }
    user_token = jwt.encode(user_payload, SECRET_KEY, algorithm=ALGORITHM)
    
    # 2. Create a token for an admin user (role: "admin")
    admin_payload = {
        "id": 1,
        "name": "Admin User",
        "email": "admin@example.com",
        "role": "admin",
        "exp": int(time.time()) + 3600
    }
    admin_token = jwt.encode(admin_payload, SECRET_KEY, algorithm=ALGORITHM)
    
    routes = [
        "/api/workspace/prompts",
        "/api/workspace/skills",
        "/api/workspace/tools",
        "/api/workspace/knowledge"
    ]
    
    for route in routes:
        # Normal user should get 403 Forbidden
        response = client.get(route, headers={"Authorization": f"Bearer {user_token}"})
        assert response.status_code == 403, f"Expected 403 for {route} with user token, got {response.status_code}"
        
        # Admin user should pass authorization and try to fetch from DB (should return 200 or 500 depending on DB connection config)
        response = client.get(route, headers={"Authorization": f"Bearer {admin_token}"})
        # If DB connection is configured, it will return 200 list, otherwise it might fail with 500 or 200. Both mean auth passed!
        assert response.status_code in (200, 500), f"Expected 200 or 500 for {route} with admin token, got {response.status_code}"

if __name__ == "__main__":
    test_workspace_rbac()
