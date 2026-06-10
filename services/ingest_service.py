import numpy as np
from psycopg2.extras import execute_values
from database.db import get_conn
from services.embed_service import embed
from retrieval.chunking import simple_semantic_chunk
from utils.text_cleaner import clean_text


def ingest_document(text: str, reset: bool = False):

    chunks = simple_semantic_chunk(text)

    if not chunks:
        return {"status": "empty", "chunks": 0}

    embeddings = embed(chunks)

    conn = get_conn()
    cur = conn.cursor()

    try:
        if reset:
            cur.execute("DELETE FROM documents")

        data = [
            (
                chunk,
                emb.tolist() if isinstance(emb, np.ndarray) else emb,
                chunk
            )
            for chunk, emb in zip(chunks, embeddings)
        ]

        execute_values(
            cur,
            """
            INSERT INTO documents (chunk, embedding, content_tsv)
            VALUES %s
            """,
            data
        )

        conn.commit()

        return {
            "status": "success",
            "chunks": len(chunks)
        }

    except Exception as e:
        conn.rollback()
        return {
            "status": "error",
            "error": str(e)
        }

    finally:
        cur.close()
        conn.close()
