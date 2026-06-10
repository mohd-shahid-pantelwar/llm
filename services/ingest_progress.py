from database.db import get_conn
from services.embed_service import embed
from retrieval.chunking import simple_semantic_chunk
from progress_service import update_progress


def ingest_document_with_progress(text: str, job_id: str):

    chunks = simple_semantic_chunk(text)
    embeddings = embed(chunks)

    total = len(chunks)

    conn = get_conn()
    cur = conn.cursor()

    try:
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):

            cur.execute(
                """
                INSERT INTO documents (chunk, embedding, content_tsv)
                VALUES (%s, %s, to_tsvector(%s))
                """,
                (
                    chunk,
                    emb.tolist() if hasattr(emb, "tolist") else emb,
                    chunk
                )
            )

            conn.commit()

            update_progress(job_id, i + 1, total)

        return {"status": "completed"}

    except Exception as e:
        conn.rollback()
        return {"status": "error", "error": str(e)}

    finally:
        cur.close()
        conn.close()