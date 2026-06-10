import numpy as np

def normalize_embedding(embedding):
    if isinstance(embedding, np.ndarray):
        return embedding.astype(np.float32).tolist()
    return embedding