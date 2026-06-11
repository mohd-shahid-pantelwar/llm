import hashlib
import json
import numpy as np
from typing import List

from retrieval.search import hybrid_search
from database.redis import cache_get, cache_set
from services.embed_service import embed
from services.llm_service import LLMService
from retrieval.rerank import rerank
from database.db import get_conn

llm = LLMService()


def build_cache_key(query: str, knowledge_id: str = None, file_id: str = None):
    key_str = f"{query}:{knowledge_id}:{file_id}" if file_id else (f"{query}:{knowledge_id}" if knowledge_id else query)
    return hashlib.md5(key_str.encode()).hexdigest()


async def ask(query: str, top_k: int = 5, model: str = "gemma3:latest", knowledge_id: str = None, file_id: str = None, system_prompt: str = None):

    cache_key = build_cache_key(query, knowledge_id, file_id)

    cached = cache_get(cache_key)
    if cached:
        return json.loads(cached)

    top_docs = []

    # 1. If knowledge_id is provided, perform search specifically on the files in that collection
    if knowledge_id:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT content FROM knowledge WHERE id = %s", (knowledge_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()

        if row and row[0]:
            try:
                files_list = json.loads(row[0])
                chunks = []
                for f in files_list:
                    if file_id and f.get("id") != file_id:
                        continue
                    text = f.get("data", "")
                    if text:
                        # Split text into chunks of 500 characters, with 100 char overlap
                        chunk_size = 500
                        overlap = 100
                        start = 0
                        while start < len(text):
                            end = start + chunk_size
                            chunk = text[start:end].strip()
                            if chunk:
                                chunks.append(chunk)
                            start += chunk_size - overlap

                if chunks:
                    query = correct_query_typos(query, chunks)
                    # Compute query embedding
                    q_emb = embed([query])[0]
                    q_vec = np.array(q_emb)
                    q_norm = np.linalg.norm(q_vec)
                    if q_norm > 0:
                        q_vec = q_vec / q_norm

                    # Compute embeddings for all chunks
                    chunk_embs = embed(chunks)

                    scores = []
                    for i, (chunk, emb) in enumerate(zip(chunks, chunk_embs)):
                        emb_vec = np.array(emb)
                        emb_norm = np.linalg.norm(emb_vec)
                        if emb_norm > 0:
                            emb_vec = emb_vec / emb_norm
                        score = float(np.dot(q_vec, emb_vec))
                        scores.append((chunk, score))

                    # Sort by score descending
                    scores.sort(key=lambda x: x[1], reverse=True)

                    # Convert to doc format
                    top_docs = [
                        {"id": f"kb-chunk-{i}", "chunk": item[0], "score": item[1]}
                        for i, item in enumerate(scores[:top_k])
                    ]
            except Exception as e:
                print(f"Error doing RAG on knowledge base {knowledge_id}: {e}")

    # 2. If no knowledge_id or no chunks found in the collection, fallback to global hybrid search
    if not top_docs:
        # embed query
        q_emb = embed([query])[0]

        # hybrid search (vector + keyword)
        conn = get_conn()
        docs = hybrid_search(conn, q_emb, query, top_k=20)
        conn.close()

        # format docs
        docs = [
            {"id": d[0], "chunk": d[1], "score": d[2]}
            for d in docs
        ]

        # rerank
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

    # Resolve system prompt placeholders if they exist
    if system_prompt:
        try:
            if "{context}" in system_prompt:
                system_prompt = system_prompt.replace("{context}", context)
            if "{question}" in system_prompt:
                system_prompt = system_prompt.replace("{question}", query)
            if "{query}" in system_prompt:
                system_prompt = system_prompt.replace("{query}", query)
        except Exception as e:
            print("Error resolving system prompt placeholders:", e)

    # 5. LLM call
    local_llm = LLMService(model=model)
    res_data = await local_llm.generate(prompt, system_prompt=system_prompt)

    result = {
        "query": query,
        "answer": res_data.get("response", ""),
        "stats": res_data.get("stats", {}),
        "sources": top_docs
    }

    cache_set(cache_key, json.dumps(result))

    return result


def correct_query_typos(query: str, chunks: List[str]) -> str:
    import re
    words = set()
    for chunk in chunks:
        for w in re.findall(r'[a-zA-Z]{4,}', chunk.lower()):
            words.add(w)
            
    query_words = query.split()
    corrected_words = []
    for qw in query_words:
        clean_qw = re.sub(r'[^a-zA-Z]', '', qw).lower()
        if not clean_qw or len(clean_qw) <= 3:
            corrected_words.append(qw)
            continue
            
        if clean_qw in words:
            corrected_words.append(qw)
            continue
            
        best_match = clean_qw
        best_dist = 3
        for w in words:
            dist = edit_distance(clean_qw, w)
            if dist < best_dist:
                best_dist = dist
                best_match = w
                
        if best_dist <= 1:
            corrected_words.append(qw.replace(clean_qw, best_match))
        else:
            corrected_words.append(qw)
            
    return " ".join(corrected_words)


def edit_distance(s1, s2):
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2+1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(1 + min((distances[i1], distances[i1 + 1], distances_[-1])))
        distances = distances_
    return distances[-1]