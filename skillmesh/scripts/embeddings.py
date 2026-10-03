"""Text -> vector conversion, backed by pgvector-compatible 384-dim floats.

Primary path
------------
`sentence-transformers` model **all-MiniLM-L6-v2**: a 6-layer MiniLM encoder with
384-dim output. It is small (~80 MB), CPU-friendly and produces embeddings in
which semantically similar sentences land close together under cosine
distance - exactly what scripts/match.py needs.

Fallback path
-------------
If sentence-transformers (or torch) is not installed - or the model cannot be
downloaded because the machine is offline - we fall back to a deterministic
lexical vectoriser (word unigrams + bigrams, hashed into the same 384
dimensions). It is NOT semantic, but it is deterministic, dependency-free and
still gives sane cosine scores so the demo and the test-suite remain runnable.
`BACKEND` tells you which one is active.
"""

import hashlib
import math
import os
import re

try:  # normalise imports for both `python scripts/x.py` and `import scripts.x`
    from .config import EMBEDDING_DIM, EMBEDDING_MODEL
except ImportError:  # pragma: no cover
    from config import EMBEDDING_DIM, EMBEDDING_MODEL

_model = None
BACKEND = "uninitialised"

_TOKEN_RE = re.compile(r"[a-z0-9+#]+")


def _hash_index(token: str, dim: int):
    """Stable (not Python-hash) bucket + sign for the hashing trick."""
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, (1.0 if (value >> 63) & 1 else -1.0)


def _fallback_embed(text: str, dim: int = EMBEDDING_DIM):
    tokens = _TOKEN_RE.findall(text.lower())
    vector = [0.0] * dim
    if not tokens:
        vector[0] = 1.0
        return vector

    bigrams = [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    for token in tokens:
        idx, sign = _hash_index(token, dim)
        vector[idx] += sign
    for bigram in bigrams:
        idx, sign = _hash_index(bigram, dim)
        vector[idx] += sign * 0.6

    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [v / norm for v in vector]


def _load_model():
    global _model, BACKEND
    if _model is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(EMBEDDING_MODEL)
        BACKEND = "sentence-transformers"
    except Exception as exc:  # ImportError, download failure, torch problems...
        _model = False
        BACKEND = f"lexical-fallback ({type(exc).__name__})"
    return _model


def backend():
    """Name of the active backend, loading the model on first call."""
    _load_model()
    return BACKEND


def embed(text: str):
    """Embed `text` and return exactly EMBEDDING_DIM floats."""
    model = _load_model()
    if model is False:
        return _fallback_embed(text)

    vector = model.encode(text, convert_to_numpy=True).astype(float).tolist()
    assert len(vector) == EMBEDDING_DIM, (
        f"expected {EMBEDDING_DIM}-dim embedding, got {len(vector)}"
    )
    return vector


def embedding_literal(vector):
    """Render a vector as a pgvector literal, e.g. '[0.1,0.2,...]'.

    Used by the psycopg3 adapter registered below; passing a Python list
    directly also works because psycopg adapts list[float] to a numeric[] which
    the vector type accepts via its input function. The literal keeps the SQL
    portable and readable in logs.
    """
    return "[" + ",".join(f"{v:.8f}" for v in vector) + "]"


if __name__ == "__main__":  # pragma: no cover - manual smoke test
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    sample = "I teach advanced Python programming"
    vec = embed(sample)
    print(f"backend : {BACKEND}")
    print(f"model   : {EMBEDDING_MODEL}")
    print(f"dims    : {len(vec)}")
    print(f"sample  : {[round(v, 4) for v in vec[:8]]} ...")