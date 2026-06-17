from database.db import get_conn
import numpy as np
from retrieval.vector_utils import normalize_embedding

def search(query_embedding, top_k=5):
    query_embedding = normalize_embedding(query_embedding)
    conn = get_conn()
    cur = conn.cursor()

    # convert numpy → list → pgvector format
    if isinstance(query_embedding, np.ndarray):
        query_embedding = query_embedding.tolist()

    cur.execute("""
        SELECT chunk
        FROM documents
        ORDER BY embedding <=> %s%s::vector
        LIMIT %s
    """, (query_embedding, top_k))

    results = cur.fetchall()

    cur.close()
    conn.close()

    return [row[0] for row in results]
def hybrid_search(conn, query_embedding, query_text, top_k=5):
     
    query_embedding = normalize_embedding(query_embedding)

    cur = conn.cursor()

    cur.execute("""
        SELECT
            id,
            chunk,
            1 - (embedding <=> %s::vector) AS vector_score,
            ts_rank(content_tsv, plainto_tsquery(%s)) AS text_score
        FROM documents
        ORDER BY (
            0.7 * (1 - (embedding <=> %s::vector)) +
            0.3 * ts_rank(content_tsv, plainto_tsquery(%s))
        ) DESC
        LIMIT %s
    """, (
        query_embedding,
        query_text,
        query_embedding,
        query_text,
        top_k * 3
    ))

    results = cur.fetchall()
    
    filtered_results = []
    for r in results:
        vector_score = float(r[2]) if r[2] is not None else 0.0
        text_score = float(r[3]) if r[3] is not None else 0.0
        combined_score = 0.7 * vector_score + 0.3 * text_score
        
        # Apply minimum similarity threshold of 0.4
        if combined_score >= 0.4 and is_good_chunk(r[1]):
            filtered_results.append((r[0], r[1], combined_score))
            
    return filtered_results[:top_k]


def is_good_chunk(text: str):

    bad_signals = [
        "Common Mistakes",
        "[!",
        "01_",
        "introduction_and_basics"
    ]

    return not any(b in text for b in bad_signals)