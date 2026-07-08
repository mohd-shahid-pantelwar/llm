"""Query typo correction: SymSpell candidate lookup + char-BiLSTM ranking.

SymSpell gives instant edit-distance candidates from the document vocabulary.
The LSTM (trained on synthetic typos generated from that same vocabulary)
picks the best candidate when SymSpell is ambiguous — its bidirectional pass
over the characters captures short-term context that plain edit distance
can't (e.g. "tet" → "test" rather than "ten").
An edit-distance guard keeps the model from inventing wild corrections.
"""

import json
import os
import random
import re
import threading
from collections import Counter

from database.db import get_conn
from database.redis import r as redis_client

MODEL_DIR = os.path.join("data", "typo_model")
VOCAB_PATH = os.path.join(MODEL_DIR, "vocab.json")
MODEL_PATH = os.path.join(MODEL_DIR, "lstm.pt")
STATUS_KEY = "admin:typo:trainStatus"

CHARS = "abcdefghijklmnopqrstuvwxyz"
CHAR2IDX = {c: i + 1 for i, c in enumerate(CHARS)}  # 0 = padding
MAX_WORD_LEN = 20
MAX_VOCAB = 8000

KEYBOARD_NEIGHBORS = {
    "q": "wa", "w": "qes", "e": "wrd", "r": "etf", "t": "ryg", "y": "tuh",
    "u": "yij", "i": "uok", "o": "ipl", "p": "ol", "a": "qsz", "s": "awdx",
    "d": "sefc", "f": "drgv", "g": "fthb", "h": "gyjn", "j": "hukm",
    "k": "jil", "l": "kop", "z": "asx", "x": "zsdc", "c": "xdfv",
    "v": "cfgb", "b": "vghn", "n": "bhjm", "m": "njk",
}

_lock = threading.Lock()
_symspell = None
_vocab = None
_lstm = None
_lstm_words = None


def edit_distance(s1: str, s2: str) -> int:
    if len(s1) < len(s2):
        return edit_distance(s2, s1)
    if not s2:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        cur = [i + 1]
        for j, c2 in enumerate(s2):
            cur.append(min(prev[j + 1] + 1, cur[j] + 1, prev[j] + (c1 != c2)))
        prev = cur
    return prev[-1]


# ─── Vocabulary ────────────────────────────────────────────────────────────────

def build_vocab(max_words: int = MAX_VOCAB) -> dict:
    """Word frequencies from ingested documents AND knowledge-base files."""
    counts = Counter()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT chunk FROM documents")
    texts = [row[0] or "" for row in cur.fetchall()]
    cur.execute("SELECT content FROM knowledge")
    for (content,) in cur.fetchall():
        if not content:
            continue
        try:
            for f in json.loads(content):
                texts.append(f.get("data", "") or "")
        except Exception:
            pass
    cur.close()
    conn.close()

    for text in texts:
        for w in re.findall(r"[a-zA-Z]{3,20}", text.lower()):
            counts[w] += 1
    return dict(counts.most_common(max_words))


def _get_vocab() -> dict:
    global _vocab
    if _vocab is None:
        with _lock:
            if _vocab is None:
                if os.path.exists(VOCAB_PATH):
                    with open(VOCAB_PATH) as f:
                        _vocab = json.load(f)
                else:
                    _vocab = build_vocab()
    return _vocab


def _get_symspell():
    global _symspell
    if _symspell is None:
        with _lock:
            if _symspell is None:
                from symspellpy import SymSpell
                ss = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
                for w, c in _get_vocab().items():
                    ss.create_dictionary_entry(w, c)
                _symspell = ss
    return _symspell


# ─── LSTM model ────────────────────────────────────────────────────────────────

def _encode(word: str):
    import torch
    idx = [CHAR2IDX.get(c, 0) for c in word[:MAX_WORD_LEN]]
    idx += [0] * (MAX_WORD_LEN - len(idx))
    return torch.tensor(idx, dtype=torch.long)


def _build_model(n_classes: int):
    import torch.nn as nn

    class TypoLSTM(nn.Module):
        def __init__(self):
            super().__init__()
            self.emb = nn.Embedding(len(CHARS) + 1, 24, padding_idx=0)
            self.lstm = nn.LSTM(24, 96, batch_first=True, bidirectional=True)
            self.fc = nn.Linear(96 * 2, n_classes)

        def forward(self, x):
            e = self.emb(x)
            _, (h, _) = self.lstm(e)
            return self.fc(__import__("torch").cat([h[0], h[1]], dim=1))

    return TypoLSTM()


def _make_typos(word: str, rng: random.Random, n: int = 3):
    out = set()
    for _ in range(n * 3):
        if len(out) >= n:
            break
        w = list(word)
        op = rng.choice(["delete", "swap", "replace", "insert"])
        pos = rng.randrange(len(w))
        if op == "delete" and len(w) > 2:
            del w[pos]
        elif op == "swap" and pos < len(w) - 1:
            w[pos], w[pos + 1] = w[pos + 1], w[pos]
        elif op == "replace":
            w[pos] = rng.choice(KEYBOARD_NEIGHBORS.get(w[pos], CHARS))
        elif op == "insert":
            w.insert(pos, rng.choice(KEYBOARD_NEIGHBORS.get(w[pos], CHARS)))
        typo = "".join(w)
        if typo != word:
            out.add(typo)
    return out


def train(epochs: int = 4, max_words: int = MAX_VOCAB):
    """Train the char-BiLSTM on synthetic typos from the corpus vocabulary."""
    global _vocab, _symspell, _lstm, _lstm_words
    import torch
    import torch.nn as nn

    redis_client.set(STATUS_KEY, json.dumps({"status": "building vocabulary"}), ex=86400)
    vocab = build_vocab(max_words)
    words = list(vocab.keys())
    if len(words) < 50:
        redis_client.set(STATUS_KEY, json.dumps({"status": "error", "error": "not enough corpus words to train"}), ex=86400)
        return

    rng = random.Random(42)
    xs, ys = [], []
    for ci, w in enumerate(words):
        xs.append(_encode(w))
        ys.append(ci)
        for typo in _make_typos(w, rng):
            xs.append(_encode(typo))
            ys.append(ci)

    X = torch.stack(xs)
    y = torch.tensor(ys, dtype=torch.long)
    perm = torch.randperm(len(X))
    X, y = X[perm], y[perm]

    model = _build_model(len(words))
    opt = torch.optim.Adam(model.parameters(), lr=2e-3)
    loss_fn = nn.CrossEntropyLoss()
    batch = 256

    model.train()
    for epoch in range(epochs):
        total, correct, seen = 0.0, 0, 0
        for i in range(0, len(X), batch):
            xb, yb = X[i:i + batch], y[i:i + batch]
            opt.zero_grad()
            out = model(xb)
            loss = loss_fn(out, yb)
            loss.backward()
            opt.step()
            total += float(loss) * len(xb)
            correct += int((out.argmax(1) == yb).sum())
            seen += len(xb)
        acc = correct / max(seen, 1)
        redis_client.set(STATUS_KEY, json.dumps(
            {"status": "training", "epoch": epoch + 1, "epochs": epochs, "accuracy": round(acc, 3)}), ex=86400)
        print(f"[Typo LSTM] epoch {epoch + 1}/{epochs} loss={total / seen:.3f} acc={acc:.3f}")

    os.makedirs(MODEL_DIR, exist_ok=True)
    torch.save(model.state_dict(), MODEL_PATH)
    with open(VOCAB_PATH, "w") as f:
        json.dump(vocab, f)

    with _lock:
        _vocab, _symspell, _lstm, _lstm_words = vocab, None, None, None
    redis_client.set(STATUS_KEY, json.dumps(
        {"status": "success", "vocabWords": len(words), "samples": len(X), "accuracy": round(acc, 3)}), ex=86400)


def _get_lstm():
    global _lstm, _lstm_words
    if _lstm is None and os.path.exists(MODEL_PATH) and os.path.exists(VOCAB_PATH):
        with _lock:
            if _lstm is None:
                import torch
                with open(VOCAB_PATH) as f:
                    words = list(json.load(f).keys())
                model = _build_model(len(words))
                model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu"))
                model.eval()
                _lstm, _lstm_words = model, words
    return _lstm, _lstm_words


def _lstm_predict(word: str):
    model, words = _get_lstm()
    if model is None:
        return None, 0.0
    import torch
    with torch.no_grad():
        probs = torch.softmax(model(_encode(word).unsqueeze(0))[0], dim=0)
        p, ci = torch.max(probs, dim=0)
        return words[int(ci)], float(p)


# ─── Public API ────────────────────────────────────────────────────────────────

def correct_word(word: str) -> str:
    clean = word.lower()
    if not re.fullmatch(r"[a-zA-Z]{3,20}", clean):
        return word
    vocab = _get_vocab()
    if clean in vocab:
        return word

    from symspellpy import Verbosity
    suggestions = _get_symspell().lookup(clean, Verbosity.CLOSEST, max_edit_distance=2)
    candidates = [s.term for s in suggestions]

    # LSTM ranks; edit-distance guard stops wild predictions
    pred, prob = _lstm_predict(clean)
    if pred and prob >= 0.5 and edit_distance(clean, pred) <= 2:
        if not candidates or pred in candidates or prob >= 0.8:
            return pred

    if candidates:
        return candidates[0]
    return word


def correct_query(query: str) -> str:
    corrected = []
    for token in query.split():
        m = re.match(r"^([a-zA-Z]+)(.*)$", token)
        if m:
            fixed = correct_word(m.group(1))
            corrected.append(fixed + m.group(2) if fixed != m.group(1) else token)
        else:
            corrected.append(token)
    result = " ".join(corrected)
    if result != query:
        print(f"[Typo] corrected query: '{query}' -> '{result}'")
    return result
