import hashlib
import json
import numpy as np
from typing import List

from retrieval.search import hybrid_search
from database.redis import cache_get, cache_set
from services.embed_service import embed, async_embed
from services.llm_service import LLMService
from retrieval.rerank import rerank
from database.db import get_conn

llm = LLMService()


def build_cache_key(query: str, knowledge_id: str = None, file_id: str = None, system_prompt: str = None, history: list = None, user_id: str = None):
    key_str = f"user_{user_id}:{query}:{knowledge_id}:{file_id}:{system_prompt}"
    if history:
        # Just hash the string representation of history to ensure uniqueness
        key_str += f":{str(history)}"
    return hashlib.md5(key_str.encode()).hexdigest()


async def retrieve_context_docs(query: str, top_k: int = 5, knowledge_id: str = None, file_id: str = None, model: str = "gemma3:latest"):
    top_docs = []

    # 0. Self-RAG Router: Let LLM decide if retrieval is needed
    router_prompt = f"""You are a routing assistant. Your ONLY job is to decide if the following user query requires searching an external knowledge base or database for facts, context, or code.
If it is a simple greeting, conversational phrase, or a general question that requires NO external facts, reply with exactly the word "NO".
If it asks about specific data, logs, code, facts, files, or technical concepts that might be in a document, reply with exactly the word "YES".

User Query: "{query}"
Decision (YES/NO):"""
    try:
        router_llm = LLMService(model=model)
        # One-word decision: cap output so the router can't ramble
        router_res = await router_llm.generate(router_prompt, options={"num_predict": 6})
        answer = router_res.get("response", "").strip().lower()
        if "no" in answer and "yes" not in answer:
            print(f"[Self-RAG] Skipping retrieval for query: '{query}'")
            return top_docs, query
        print(f"[Self-RAG] Proceeding with retrieval for query: '{query}'")
    except Exception as e:
        print(f"Self-RAG Router Error: {e}")

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
                chunk_embs = []
                for f in files_list:
                    if file_id and f.get("id") != file_id:
                        continue
                    text = f.get("data", "")
                    if not text:
                        continue

                    # Try to get cached chunks and embeddings from Redis
                    import hashlib
                    content_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
                    file_cache_key = f"file_embs:{f.get('id', '')}:{content_hash}"
                    
                    cached_data = cache_get(file_cache_key)
                    if cached_data:
                        try:
                            if isinstance(cached_data, str):
                                file_records = json.loads(cached_data)
                            else:
                                file_records = cached_data
                            
                            for chunk, emb in file_records:
                                chunks.append((f.get("name", "Unknown File"), chunk))
                                chunk_embs.append(emb)
                            continue
                        except Exception as ce:
                            print(f"Error reading cached embeddings: {ce}")

                    # Fallback to computing chunks and embeddings if not cached
                    file_chunks = []
                    chunk_size = 500
                    overlap = 100
                    start = 0
                    while start < len(text):
                        end = start + chunk_size
                        chunk = text[start:end].strip()
                        if chunk:
                            file_chunks.append(chunk)
                        start += chunk_size - overlap
                    
                    if file_chunks:
                        file_embs = await async_embed(file_chunks)
                        file_records = list(zip(file_chunks, file_embs))
                        cache_set(file_cache_key, file_records, ttl=30 * 24 * 3600)
                        
                        for chunk, emb in file_records:
                            chunks.append((f.get("name", "Unknown File"), chunk))
                            chunk_embs.append(emb)

                if chunks:
                    chunk_texts = [c[1] for c in chunks]
                    query = correct_query_typos(query, chunk_texts)
                    # Compute query embedding
                    q_emb = (await async_embed([query]))[0]
                    q_vec = np.array(q_emb)
                    q_norm = np.linalg.norm(q_vec)
                    if q_norm > 0:
                        q_vec = q_vec / q_norm

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

                    # Convert to doc format and apply threshold
                    top_docs = []
                    for i, item in enumerate(scores):
                        if item[1] >= 0.4:
                            top_docs.append({"id": item[0][0], "chunk": item[0][1], "score": item[1]})
                        if len(top_docs) >= top_k:
                            break
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"Error doing RAG on knowledge base {knowledge_id}: {e}")

    # 2. If no knowledge_id or no chunks found in the collection, fallback to global hybrid search
    if not top_docs:
        # embed query
        q_emb = (await async_embed([query]))[0]

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

    return top_docs, query


async def ask(query: str, top_k: int = 5, model: str = "gemma3:latest", knowledge_id: str = None, file_id: str = None, system_prompt: str = None, history: list = None, user_id: str = None):
    cache_key = build_cache_key(query, knowledge_id, file_id, system_prompt, history, user_id)

    cached = cache_get(cache_key)
    if cached:
        return json.loads(cached)

    top_docs, corrected_query = await retrieve_context_docs(query, top_k, knowledge_id, file_id, model=model)
    
    # Deduplicate filenames for context preamble
    unique_filenames = list(dict.fromkeys(d["id"] for d in top_docs))
    context = ""
    for d in top_docs:
        chunk_text = d['chunk']
        if chunk_text.startswith("FILE_REFERENCE:["):
            import re
            match = re.search(r"FILE_REFERENCE:\[(.*?)\]", chunk_text)
            if match:
                ref_filename = match.group(1)
                try:
                    from storage.minio_client import get_file
                    file_bytes = get_file(ref_filename)
                    minio_content = file_bytes.decode("utf-8", errors="ignore")
                    chunk_text = f"--- Content from {ref_filename} ---\n{minio_content}"
                    print(f"🔥 LAZY LOAD SUCCESS: Intercepted FILE_REFERENCE and injected {len(minio_content)} bytes of logs from {ref_filename}!")
                    
                    # dynamically queue this bucket to be permanently embedded into the Vector Store!
                    try:
                        conn = get_conn()
                        cur = conn.cursor()
                        cur.execute("SELECT status FROM ingestion_jobs WHERE file_name = %s", (ref_filename,))
                        if not cur.fetchone():
                            print(f"[rag-api] ♻️ Queueing Lazy-Loaded bucket {ref_filename} for permanent Vector DB embedding...")
                            from workers.queue import queue
                            queue.enqueue("workers.ingest_worker.process_file", ref_filename, job_timeout="2h")
                        conn.close()
                    except Exception as q_err:
                        print(f"Failed to queue lazy loaded file for embedding: {q_err}")
                except Exception as e:
                    print(f"Failed to lazy load {ref_filename} from Minio: {e}")
                    
        context += f"Source: {d['id']}\n{chunk_text}\n\n"

    # 4. prompt
    prompt = ""
    if not system_prompt:
        if context:
            prompt += "You are a helpful assistant. Use the provided context to answer the question if it is relevant. If the context does not contain the answer, rely on your general knowledge to assist the user.\n\n"
        else:
            prompt += "You are a helpful assistant.\n\n"
    elif not context:
        prompt += "System Note: No context documents were found or needed for this query. You MUST ignore any instructions in your system prompt that tell you to say 'Not found in provided context' or to refuse answering. Respond to the user conversationally using your general knowledge.\n\n"
            
    if context:
        if not system_prompt or "{context}" not in system_prompt:
            prompt += f"Context:\n{context}\n\n"
    
    if history:
        prompt += "Conversation history:\n"
        for msg in history:
            sender = getattr(msg, "sender", None) or (msg.get("sender") if isinstance(msg, dict) else "")
            content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else "")
            role = "User" if sender == "user" else "Assistant"
            prompt += f"{role}: {content}\n"
        prompt += "\n"

    prompt += f"Question:\n{corrected_query}"

    # Resolve system prompt placeholders if they exist
    if system_prompt:
        try:
            if "{context}" in system_prompt:
                system_prompt = system_prompt.replace("{context}", context)
            if "{question}" in system_prompt:
                system_prompt = system_prompt.replace("{question}", corrected_query)
            if "{query}" in system_prompt:
                system_prompt = system_prompt.replace("{query}", corrected_query)
        except Exception as e:
            print("Error resolving system prompt placeholders:", e)

    # Calculate RAG retrieval confidence score (average of top_k vector matches)
    retrieval_confidence = sum(d['score'] for d in top_docs) / len(top_docs) if top_docs else 0.0
    print(f"\n[RAG] Query: '{corrected_query}' | Retrieval Confidence Score: {retrieval_confidence:.2f}\n")

    # 5. LLM call
    local_llm = LLMService(model=model)
    res_data = await local_llm.generate(prompt, system_prompt=system_prompt)
    
    stats = res_data.get("stats", {})
    stats["confidence_score"] = retrieval_confidence

    result = {
        "query": corrected_query,
        "answer": res_data.get("response", ""),
        "stats": stats,
        "sources": top_docs
    }

    cache_set(cache_key, json.dumps(result))

    return result


async def ask_stream(query: str, top_k: int = 5, model: str = "gemma3:latest", knowledge_id: str = None, file_id: str = None, system_prompt: str = None, history: list = None, user_id: str = None):
    cache_key = build_cache_key(query, knowledge_id, file_id, system_prompt, history, user_id)

    cached = cache_get(cache_key)
    if cached:
        cached_data = json.loads(cached)
        yield {
            "response": cached_data.get("answer", ""),
            "done": True,
            "stats": cached_data.get("stats", {}),
            "sources": cached_data.get("sources", [])
        }
        return

    top_docs, corrected_query = await retrieve_context_docs(query, top_k, knowledge_id, file_id, model=model)
    
    unique_filenames = list(dict.fromkeys(d["id"] for d in top_docs))
    context = ""
    for d in top_docs:
        chunk_text = d['chunk']
        if chunk_text.startswith("FILE_REFERENCE:["):
            import re
            match = re.search(r"FILE_REFERENCE:\[(.*?)\]", chunk_text)
            if match:
                ref_filename = match.group(1)
                try:
                    from storage.minio_client import get_file
                    file_bytes = get_file(ref_filename)
                    minio_content = file_bytes.decode("utf-8", errors="ignore")
                    chunk_text = f"--- Content from {ref_filename} ---\n{minio_content}"
                    print(f"🔥 LAZY LOAD SUCCESS: Intercepted FILE_REFERENCE and injected {len(minio_content)} bytes of logs from {ref_filename}!")
                    
                    # dynamically queue this bucket to be permanently embedded into the Vector Store!
                    try:
                        conn = get_conn()
                        cur = conn.cursor()
                        cur.execute("SELECT status FROM ingestion_jobs WHERE file_name = %s", (ref_filename,))
                        if not cur.fetchone():
                            print(f"[rag-api] ♻️ Queueing Lazy-Loaded bucket {ref_filename} for permanent Vector DB embedding...")
                            from workers.queue import queue
                            queue.enqueue("workers.ingest_worker.process_file", ref_filename, job_timeout="2h")
                        conn.close()
                    except Exception as q_err:
                        print(f"Failed to queue lazy loaded file for embedding: {q_err}")
                except Exception as e:
                    print(f"Failed to lazy load {ref_filename} from Minio: {e}")
                    
        context += f"Source: {d['id']}\n{chunk_text}\n\n"

    prompt = ""
    if not system_prompt:
        if context:
            prompt += "You are a helpful assistant. Use the provided context to answer the question if it is relevant. If the context does not contain the answer, rely on your general knowledge to assist the user.\n\n"
        else:
            prompt += "You are a helpful assistant.\n\n"
    elif not context:
        prompt += "System Note: No context documents were found or needed for this query. You MUST ignore any instructions in your system prompt that tell you to say 'Not found in provided context' or to refuse answering. Respond to the user conversationally using your general knowledge.\n\n"
            
    if context:
        if not system_prompt or "{context}" not in system_prompt:
            prompt += f"Context:\n{context}\n\n"
    
    if history:
        prompt += "Conversation history:\n"
        for msg in history:
            sender = getattr(msg, "sender", None) or (msg.get("sender") if isinstance(msg, dict) else "")
            content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else "")
            role = "User" if sender == "user" else "Assistant"
            prompt += f"{role}: {content}\n"
        prompt += "\n"

    prompt += f"Question:\n{corrected_query}"

    if system_prompt:
        try:
            if "{context}" in system_prompt:
                system_prompt = system_prompt.replace("{context}", context)
            if "{question}" in system_prompt:
                system_prompt = system_prompt.replace("{question}", corrected_query)
            if "{query}" in system_prompt:
                system_prompt = system_prompt.replace("{query}", corrected_query)
        except Exception as e:
            print("Error resolving system prompt placeholders:", e)

    local_llm = LLMService(model=model)
    full_response = ""
    last_stats = {}
    
    # Calculate RAG retrieval confidence score (average of top_k vector matches)
    retrieval_confidence = sum(d['score'] for d in top_docs) / len(top_docs) if top_docs else 0.0
    print(f"\n[RAG] Query: '{corrected_query}' | Retrieval Confidence Score: {retrieval_confidence:.2f}\n")

    async for chunk in local_llm.generate_stream(prompt, system_prompt=system_prompt):
        full_response += chunk.get("response", "")
        if chunk.get("stats"):
            last_stats = chunk["stats"]
            last_stats["confidence_score"] = retrieval_confidence
        
        # Include sources on the first chunk or all chunks, let's include on all/first chunk for client visibility
        chunk["sources"] = top_docs
        
        # Inject the confidence score into the chunk's stats stream so the UI can see it immediately
        if "stats" not in chunk or not chunk["stats"]:
            chunk["stats"] = {}
        chunk["stats"]["confidence_score"] = retrieval_confidence
        
        yield chunk

    result = {
        "query": corrected_query,
        "answer": full_response,
        "stats": last_stats,
        "sources": top_docs
    }
    cache_set(cache_key, json.dumps(result))


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