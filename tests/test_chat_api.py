import sys
import os
import jwt
import time
from unittest.mock import patch, AsyncMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from main import app
from routers.auth import SECRET_KEY, ALGORITHM

client = TestClient(app)

# Generate user token
user_payload = {
    "id": 999,
    "name": "Normal User",
    "email": "user@example.com",
    "role": "user",
    "exp": int(time.time()) + 3600
}
user_token = jwt.encode(user_payload, SECRET_KEY, algorithm=ALGORITHM)
headers = {"Authorization": f"Bearer {user_token}"}

# ── Route registration tests (no auth needed to verify routing) ──────────────

def test_chat_route_registered():
    """POST /api/chat exists — returns 422 (missing body) or 401, not 404."""
    response = client.post("/api/chat", json={})
    assert response.status_code != 404, "Chat route is not registered"
    print(f"POST /api/chat (empty body) → {response.status_code} ✓")

def test_chat_model_routes_registered():
    """Model preset routes exist and return expected auth/validation codes."""
    # GET /api/models requires auth now
    response = client.get("/api/models", headers=headers)
    assert response.status_code in (200, 500), f"Unexpected: {response.status_code}"
    print(f"GET /api/models → {response.status_code} ✓")

    # POST preset needs auth → 401 or 422
    response = client.post("/api/models/preset", json={})
    assert response.status_code in (401, 422), f"Unexpected: {response.status_code}"
    print(f"POST /api/models/preset (no auth) → {response.status_code} ✓")

    # DELETE preset needs auth → 401
    response = client.delete("/api/models/preset/test-id")
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    print(f"DELETE /api/models/preset/test-id (no auth) → {response.status_code} ✓")

    # PATCH toggle needs auth → 401
    response = client.patch("/api/models/preset/test-id/toggle")
    assert response.status_code == 401, f"Expected 401, got {response.status_code}"
    print(f"PATCH /api/models/preset/test-id/toggle (no auth) → {response.status_code} ✓")

# ── Functional chat test with mocked Ollama ──────────────────────────────────

def test_chat_with_mock_ollama():
    """
    POST /api/chat with model=llama3:latest and a real query.
    LLMService.generate is mocked so the test passes when Ollama is offline.
    """
    mock_result = {
        "response": "Docker is an open platform for developing, shipping, and running applications.",
        "stats": {
            "total_duration": 1234567890,
            "eval_count": 42,
        }
    }

    async def fake_generate(self, prompt: str, system_prompt: str = None):
        return mock_result

    with patch("services.llm_service.LLMService.generate", new=fake_generate):
        response = client.post("/api/chat", json={
            "model": "llama3:latest",
            "query": "What is Docker",
            "top_k": 5,
            "use_rag": False
        }, headers=headers)

    print(f"POST /api/chat (mocked) → {response.status_code}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()
    assert "answer" in data, f"Missing 'answer' key in response: {data}"
    assert len(data["answer"]) > 0, "Answer is empty"
    print(f"Answer snippet: {data['answer'][:80]}... ✓")


async def test_rag_file_filtering():
    """
    Test that rag_service.ask filters chunks to only the file specified by file_id.
    """
    import json
    from unittest.mock import MagicMock

    mock_db_row = (json.dumps([
        {"id": "file-1", "data": "This is file one content."},
        {"id": "file-2", "data": "This is file two content."}
    ]),)

    # Mock DB connection and cursor
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchone.return_value = mock_db_row
    mock_conn.cursor.return_value = mock_cur

    # Mock embed to return simple vectors
    mock_embeddings = [[0.1] * 384] * 10

    # Mock generate response
    mock_gen_response = {"response": "Mocked answer", "stats": {}}

    with patch("services.rag_service.get_conn", return_value=mock_conn), \
         patch("services.rag_service.cache_get", return_value=None), \
         patch("services.rag_service.cache_set", return_value=None), \
         patch("services.rag_service.embed", return_value=mock_embeddings) as mock_embed, \
         patch("services.llm_service.LLMService.generate", new=AsyncMock(return_value=mock_gen_response)):
        
        # Call ask with file_id="file-2"
        from services.rag_service import ask
        res = await ask(query="test", top_k=5, knowledge_id="kb-123", file_id="file-2")
        
        # Check that we only passed "This is file two content." chunks to embed,
        # not "This is file one content."
        assert mock_embed.call_count == 2 # 1 for chunks, 1 for query
        chunk_args = mock_embed.call_args_list[0][0][0]
        # Verify that all chunks belong to file-2
        assert len(chunk_args) > 0
        for chunk in chunk_args:
            assert "file two" in chunk
            assert "file one" not in chunk

    print("RAG file-level filtering unit test passed! ✓")


def test_correct_query_typos():
    from services.rag_service import correct_query_typos
    chunks = [
        "Python is an interpreted high-level general-purpose programming language.",
        "Use print() to output messages to the console.",
        "Comments start with a hash character (#) in Python."
    ]
    # Typo: 'pythin' -> should be corrected to 'python'
    res1 = correct_query_typos("tell me about pythin", chunks)
    assert "python" in res1
    assert "pythin" not in res1

    # Typo: 'prnt' -> should be corrected to 'print'
    res2 = correct_query_typos("how to use prnt", chunks)
    assert "print" in res2
    assert "prnt" not in res2

    print("Typo correction unit test passed! ✓")


if __name__ == "__main__":
    import asyncio
    test_chat_route_registered()
    test_chat_model_routes_registered()
    test_chat_with_mock_ollama()
    asyncio.run(test_rag_file_filtering())
    test_correct_query_typos()
    print("\nAll chat API tests passed!")
