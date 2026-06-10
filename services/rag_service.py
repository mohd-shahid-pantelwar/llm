import hashlib
import json

from retrieval.search import hybrid_search
from database.redis import cache_get, cache_set
from services.embed_service import embed
from services.llm_service import LLMService
from retrieval.rerank import rerank
from database.db import get_conn

llm = LLMService()


def build_cache_key(query: str):
    return hashlib.md5(query.encode()).hexdigest()


async def ask(query: str, top_k: int = 5):

    cache_key = build_cache_key(query)

    cached = cache_get(cache_key)
    if cached:
        return json.loads(cached)

    # 1. embed
    q_emb = embed([query])[0]

    # 2. hybrid search (vector + keyword)
    conn = get_conn()
    docs = hybrid_search(conn, q_emb, query, top_k=20)

    # format docs
    docs = [
        {"id": d[0], "chunk": d[1], "score": d[2]}
        for d in docs
    ]

    # 3. rerank
    docs = rerank(query, docs)

    top_docs = docs[:5]

    context = "\n\n".join([d["chunk"] for d in top_docs])

    # 4. prompt
    prompt = f"""
You are a helpful assistant.

Context:
{context}

Question:
{query}
"""

    # 5. LLM call
    answer = await llm.generate(prompt)

    result = {
        "query": query,
        "answer": answer,
        "sources": top_docs
    }

    cache_set(cache_key, json.dumps(result))

    return result