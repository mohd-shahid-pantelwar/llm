import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app

def test_api():
    client = TestClient(app)
    
    # Check if endpoints are registered and return 401 Unauthorized (because we don't send auth headers)
    # this confirms routing works correctly
    routes = [
        "/api/workspace/prompts",
        "/api/workspace/skills",
        "/api/workspace/tools",
        "/api/workspace/knowledge"
    ]
    
    for route in routes:
        response = client.get(route)
        print(f"GET {route} response code: {response.status_code}")
        # should be 401 because get_current_user requires Bearer token
        assert response.status_code == 401, f"Expected 401 for {route}, got {response.status_code}"
        
    print("\nFastAPI workspace routing checks passed successfully!")

if __name__ == "__main__":
    test_api()
