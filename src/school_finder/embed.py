"""Local embeddings (no API key needed) via fastembed."""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from .config import settings


@lru_cache
def _model():
    from fastembed import TextEmbedding

    return TextEmbedding(settings.embed_model)


def embed(texts: list[str]) -> list[np.ndarray]:
    return [np.asarray(v, dtype=np.float32) for v in _model().embed(texts)]


def embed_query(text: str) -> np.ndarray:
    # bge models recommend a query instruction prefix for retrieval
    return embed([f"Represent this sentence for searching relevant passages: {text}"])[0]
