import requests

import os
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.0.10.131:11434")

def embed(texts):
    res = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={
            "model": "nomic-embed-text",
            "input": texts
        },
        timeout=300.0
    )
    return res.json()["embeddings"]

import httpx

async def async_embed(texts):
    async with httpx.AsyncClient(timeout=300.0) as client:
        res = await client.post(
            f"{OLLAMA_URL}/api/embed",
            json={
                "model": "nomic-embed-text",
                "input": texts
            }
        )
        res.raise_for_status()
        return res.json()["embeddings"]