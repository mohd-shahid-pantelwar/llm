import httpx
import json

import os
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://10.0.10.131:11434")


class LLMService:
    def __init__(self, model="gemma3:latest"):
        self.model = model

    async def generate(self, prompt: str, system_prompt: str = None):
        timeout = httpx.Timeout(timeout=None, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            final_prompt = prompt
            if system_prompt:
                final_prompt = f"{system_prompt}\n\n{prompt}"

            payload = {
                "model": self.model,
                "prompt": final_prompt,
                "stream": False
            }
            res = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json=payload
            )

            res.raise_for_status()
            data = res.json()
            return {
                "response": data.get("response", ""),
                "stats": {
                    "total_duration": data.get("total_duration", 0),
                    "load_duration": data.get("load_duration", 0),
                    "prompt_eval_count": data.get("prompt_eval_count", 0),
                    "prompt_eval_duration": data.get("prompt_eval_duration", 0),
                    "eval_count": data.get("eval_count", 0),
                    "eval_duration": data.get("eval_duration", 0)
                }
            }

    async def generate_stream(self, prompt: str, system_prompt: str = None):
        timeout = httpx.Timeout(timeout=None, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            final_prompt = prompt
            if system_prompt:
                final_prompt = f"{system_prompt}\n\n{prompt}"

            payload = {
                "model": self.model,
                "prompt": final_prompt,
                "stream": True
            }
            
            async with client.stream("POST", f"{OLLAMA_URL}/api/generate", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            yield {
                                "response": data.get("response", ""),
                                "done": data.get("done", False),
                                "stats": {
                                    "total_duration": data.get("total_duration", 0),
                                    "load_duration": data.get("load_duration", 0),
                                    "prompt_eval_count": data.get("prompt_eval_count", 0),
                                    "prompt_eval_duration": data.get("prompt_eval_duration", 0),
                                    "eval_count": data.get("eval_count", 0),
                                    "eval_duration": data.get("eval_duration", 0)
                                } if data.get("done") else {}
                            }
                        except Exception as e:
                            print("Error parsing stream line:", e)