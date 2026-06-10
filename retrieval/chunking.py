import re

def clean_text(text: str):
    return re.sub(r'\s+', ' ', text).strip()


def simple_semantic_chunk(text: str, max_words=120, overlap=20):

    sentences = re.split(r'(?<=[.!?]) +', text)

    chunks = []
    current = []

    current_len = 0

    for sentence in sentences:
        words = sentence.split()

        if current_len + len(words) > max_words:
            chunks.append(" ".join(current))

            # overlap (important for context continuity)
            current = current[-overlap:] if overlap < len(current) else current
            current_len = len(current)

        current.append(sentence)
        current_len += len(words)

    if current:
        chunks.append(" ".join(current))

    return [clean_text(c) for c in chunks]


def is_valid_chunk(text: str):

    if len(text.strip()) < 20:
        return False

    if "[" in text and "]" in text and "Common Mistakes" in text:
        return False

    if text.count("=") > 5:
        return False

    return True
