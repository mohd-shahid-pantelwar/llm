import httpx

OLLAMA_URL = "http://10.0.10.131:11434"


class LLMService:
    def __init__(self, model="gemma3:latest"):
        self.model = model

    async def generate(self, prompt: str):
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False
                }
            )

            res.raise_for_status()
            return res.json().get("response", "")