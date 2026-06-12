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
            }
        )
        embeddings.append(res.json()["embedding"])

    return embeddings