import httpx

import os
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.0.10.131:11434")
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
OLLAMA_NUM_THREAD = int(os.environ.get("OLLAMA_NUM_THREAD", "8"))


async def stream_llm_response(prompt: str, model="gemma3:latest"):

    async with httpx.AsyncClient(timeout=None) as client:
        async with client.stream(
            "POST",
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "stream": True,
                "keep_alive": OLLAMA_KEEP_ALIVE,
                "options": {"num_thread": OLLAMA_NUM_THREAD}
            }
        ) as res:

            async for line in res.aiter_lines():
                if not line:
                    continue

                # Ollama returns JSON lines
                import json
                try:
                    data = json.loads(line)
                    token = data.get("response", "")
                    if token:
                        yield token
                except:
                    continue