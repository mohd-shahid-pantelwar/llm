import time
import asyncio
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.rag_service import ask

async def test_rag_caching():
    print("Testing RAG caching with Python Book...")
    
    # We will query with a mock query
    t0 = time.time()
    res1 = await ask(
        query="what is dynamic typing?",
        top_k=3,
        model="gemma3:latest",
        knowledge_id="knowledge-1781173363451",
        system_prompt="Answer briefly."
    )
    t1 = time.time()
    time_first = t1 - t0
    print(f"First run took: {time_first:.4f} seconds")
    
    t0 = time.time()
    res2 = await ask(
        query="what is dynamic typing?",
        top_k=3,
        model="gemma3:latest",
        knowledge_id="knowledge-1781173363451",
        system_prompt="Answer briefly."
    )
    t2 = time.time()
    time_second = t2 - t0
    print(f"Second run took: {time_second:.4f} seconds")
    
    print("Caching speedup ratio:", time_first / max(time_second, 0.001))
    
    if "sources" in res2:
        print("Retrieved sources count:", len(res2["sources"]))
        for s in res2["sources"][:2]:
            print(f"- Chunk: {s['chunk'][:100]}")

if __name__ == "__main__":
    asyncio.run(test_rag_caching())
