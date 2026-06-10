from sentence_transformers import CrossEncoder

reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")


def rerank(query, docs):
    if not docs:
        return docs

    pairs = [(query, d["chunk"]) for d in docs]
    scores = reranker.predict(pairs)

    for i, score in enumerate(scores):
        docs[i]["rerank_score"] = float(score)

    return sorted(docs, key=lambda x: x["rerank_score"], reverse=True)