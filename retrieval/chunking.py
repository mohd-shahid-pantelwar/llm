import re

def clean_text(text: str):
    return re.sub(r'\s+', ' ', text).strip()


def simple_semantic_chunk(text: str, max_words=120, overlap=20):
    words = text.split()
    chunks = []
    
    if not words:
        return chunks
        
    for i in range(0, len(words), max_words - overlap):
        chunk_words = words[i:i + max_words]
        chunks.append(" ".join(chunk_words))
        
    return [clean_text(c) for c in chunks]


def is_valid_chunk(text: str):

    if len(text.strip()) < 20:
        return False

    if "[" in text and "]" in text and "Common Mistakes" in text:
        return False

    if text.count("=") > 5:
        return False

    return True
