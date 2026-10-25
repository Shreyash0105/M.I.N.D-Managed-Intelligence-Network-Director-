import hashlib
import re
import numpy as np
from app.core.config import settings

_model = None


def _hash_embed(text: str) -> list[float]:
    """Tiny offline fallback: hashed bag of words. Weak on meaning, fine for tests/demo without a model."""
    dims = settings.embedding_dims
    v = np.zeros(dims)
    for tok in re.findall(r"\w+", text.lower()):
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        v[h % dims] += 1.0 if (h >> 20) & 1 else -1.0
        v[(h >> 8) % dims] += 0.5
    n = np.linalg.norm(v)
    return (v / n if n else v).tolist()


def warmup():
    if settings.embedding_backend == "local":
        _load()


def _load():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed(text: str) -> list[float]:
    if settings.embedding_backend == "hash":
        return _hash_embed(text)
    return _load().encode(text, normalize_embeddings=True).tolist()


def memory_text(m: dict) -> str:
    return f"{m.get('type', 'fact')}. Topic: {m.get('topic', 'general')}. {m.get('content', '')}"
