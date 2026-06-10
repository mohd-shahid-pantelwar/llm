import re

def clean_text(text: str):

    # remove bracket metadata like [01_intro]
    text = re.sub(r"\[.*?\]", "", text)

    # remove repeated symbols
    text = re.sub(r"[#*_]{2,}", "", text)

    # remove navigation-like patterns
    text = re.sub(r"\b\d+_\w+\b", "", text)

    # normalize whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()