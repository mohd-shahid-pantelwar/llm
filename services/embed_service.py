import requests

import os
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.0.10.131:11434")

def embed(texts):
    embeddings = []

    for t in texts:
        res = requests.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={
                "model": "nomic-embed-text",
                "prompt": t
            },
            timeout=60.0
        )
        embeddings.append(res.json()["embedding"])

    return embeddings

import httpx

async def async_embed(texts):
    embeddings = []
    async with httpx.AsyncClient(timeout=120.0) as client:
        for t in texts:
            res = await client.post(
                f"{OLLAMA_URL}/api/embeddings",
                json={
                    "model": "nomic-embed-text",
                    "prompt": t
                }
            )
            res.raise_for_status()
            embeddings.append(res.json()["embedding"])
    return embeddings