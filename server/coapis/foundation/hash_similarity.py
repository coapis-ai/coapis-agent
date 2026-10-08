# -*- coding: utf-8 -*-
"""Hash-based weak semantic similarity (batch 3, D3: always on).

Character-ngram hashing into a fixed-dimensional *signed* bucket space;
cosine over the resulting L2-normalized vectors approximates lexical +
shallow structural similarity with zero model dependency.

Why signed hashing: unsigned bucket counting lets frequent shared buckets
inflate scores for unrelated texts; the random +/- sign per gram cancels
collisions in expectation, keeping cosine honest.

Works uniformly for latin and CJK text (character bigrams carry the
Chinese signal; no segmenter needed).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, List

#: Fixed vector dimension (buckets).
DIM = 256

#: Auto-promotion / near-duplicate threshold (D2 decision: 0.85).
PROMOTE_SIM_THRESHOLD = 0.85

_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """Lowercase + strip all whitespace (keeps CJK runs intact)."""
    return _WS_RE.sub("", (text or "").lower())


def _ngrams(text: str, sizes: tuple = (1, 2)) -> Iterable[str]:
    for n in sizes:
        if n <= 0:
            continue
        for i in range(max(0, len(text) - n + 1)):
            yield text[i:i + n]


def feature_vector(text: str, dim: int = DIM) -> List[float]:
    """L2-normalized signed-hash feature vector for *text*.

    Empty/whitespace-only input yields a zero vector (cosine 0 vs all).
    Deterministic across processes (blake2b, no seed).
    """
    norm = _normalize(text)
    if not norm:
        return [0.0] * dim
    vec = [0.0] * dim
    for gram in _ngrams(norm):
        digest = hashlib.blake2b(gram.encode("utf-8"), digest_size=8).digest()
        idx = int.from_bytes(digest[:4], "little") % dim
        sign = 1.0 if (digest[4] & 1) else -1.0
        vec[idx] += sign
    l2 = math.sqrt(sum(x * x for x in vec))
    if l2 <= 0:
        return [0.0] * dim
    return [x / l2 for x in vec]


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Cosine in [0, 1]; degenerate (zero) vectors score 0.0."""
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    val = dot / (math.sqrt(na) * math.sqrt(nb))
    return max(0.0, min(1.0, val))


def text_similarity(a: str, b: str, dim: int = DIM) -> float:
    """Convenience: cosine between the feature vectors of two texts."""
    return cosine_similarity(feature_vector(a, dim), feature_vector(b, dim))
