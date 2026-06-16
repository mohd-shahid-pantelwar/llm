import numpy as np
from psycopg2.extras import execute_values
from database.db import get_conn
from services.embed_service import embed
from retrieval.chunking import simple_semantic_chunk
from utils.text_cleaner import clean_text


def ingest_document(text: str, file_name: str = None, start_chunk: int = 0, reset: bool = False):
    print(f"\\n[rag-worker] Starting ingestion process... Text length: {len(text)} characters")
    
    chunks = simple_semantic_chunk(text)
    print(f"[rag-worker] Successfully split into {len(chunks)} semantic chunks. Preparing to embed in batches...")

    if not chunks:
        return {"status": "empty", "chunks": 0}

    conn = get_conn()
    cur = conn.cursor()

    if reset:
        cur.execute("DELETE FROM documents")
        conn.commit()

    batch_size = 100
    total_ingested = start_chunk

    if start_chunk > 0:
        print(f"[rag-worker] ♻️ Checkpoint found! Resuming safely from chunk {start_chunk}...")

    for i in range(start_chunk, len(chunks), batch_size):
        batch_chunks = chunks[i:i + batch_size]
        embeddings = embed(batch_chunks)

        data = [
            (
                chunk,
                emb.tolist() if isinstance(emb, np.ndarray) else emb,
                chunk
            )
            for chunk, emb in zip(batch_chunks, embeddings)
        ]

        execute_values(
            cur,
            """
            INSERT INTO documents (chunk, embedding, content_tsv)
            VALUES %s
            """,
            data,
            template="(%s, %s::vector, to_tsvector('english', %s))"
        )
        
        # Checkpoint the progress!
        if file_name:
            cur.execute("UPDATE ingestion_jobs SET chunks_processed = %s WHERE file_name = %s", (i + batch_size, file_name))
            
        conn.commit()
        total_ingested += len(batch_chunks)
        print(f"Ingested batch {i//batch_size + 1}, total {total_ingested}/{len(chunks)}")

    return {
        "status": "success",
        "chunks": total_ingested
    }

    cur.close()
    conn.close()
