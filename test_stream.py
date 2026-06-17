import asyncio
from services.rag_service import ask_stream

async def run():
    async for chunk in ask_stream("Can you show me the AppArmor Denied events please?", model="soc"):
        print(chunk.get("answer", ""), end="", flush=True)

asyncio.run(run())
