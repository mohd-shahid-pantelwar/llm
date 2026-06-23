import requests

import os
import redis
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.0.10.131:11434")

r = redis.Redis(host=os.environ.get("REDIS_HOST", "10.0.10.131"), port=int(os.environ.get("REDIS_PORT", 6379)), decode_responses=True)

def embed(texts):
    embeddings = []
    
    # Check redis for model
    db_model = r.get("admin:settings:embeddingModel")
    active_model = db_model if db_model else os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

    for t in texts:
        res = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={
                "model": active_model,
                "prompt": t
            },
            timeout=300.0
        )
        embeddings.append(res.json()["embedding"])
    return embeddings

import httpx

async def async_embed(texts):
    embeddings = []
    
    # Check redis for model
    db_model = r.get("admin:settings:embeddingModel")
    active_model = db_model if db_model else os.environ.get("EMBEDDING_MODEL", "nomic-embed-text")

    async with httpx.AsyncClient(timeout=300.0) as client:
        for t in texts:
            res = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={
                    "model": active_model,
                    "prompt": t
                }
            )
            res.raise_for_status()
            embeddings.append(res.json()["embedding"])
    return embeddings