"""Dependency-free, code-aware vectorization for local semantic ranking.

The code index keeps an index/query vector boundary without adding a model
package: identifiers,
subtokens, words, and character n-grams are projected into a stable signed
feature space and L2-normalized. The representation is deterministic,
regeneratable, and stored as a compact float32 blob in each repository target.
"""

from __future__ import annotations

import hashlib
import math
import re
from array import array

VECTOR_DIMENSIONS = 256

_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|[0-9]+")
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _features(text: str) -> list[tuple[str, float]]:
    output: list[tuple[str, float]] = []
    for raw in _WORD.findall(text):
        folded = raw.casefold()
        output.append((f"token:{folded}", 2.0))
        pieces = [
            part.casefold()
            for snake in raw.split("_")
            for part in _CAMEL_BOUNDARY.split(snake)
            if part
        ]
        output.extend((f"part:{part}", 1.5) for part in pieces)
        compact = "".join(character for character in folded if character.isalnum())
        if len(compact) >= 3:
            output.extend(
                (f"tri:{compact[index : index + 3]}", 0.35)
                for index in range(len(compact) - 2)
            )
    return output


def embed_text(text: str) -> bytes:
    """Return a stable normalized float32 vector for source or a query."""
    values = [0.0] * VECTOR_DIMENSIONS
    for feature, weight in _features(text):
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "little") % VECTOR_DIMENSIONS
        sign = 1.0 if digest[4] & 1 else -1.0
        values[bucket] += sign * weight
    norm = math.sqrt(sum(value * value for value in values))
    if norm:
        values = [value / norm for value in values]
    return array("f", values).tobytes()


def similarity(left: bytes, right: bytes) -> float:
    """Cosine similarity for normalized vectors, clamped for numeric noise."""
    if len(left) != len(right) or not left:
        return 0.0
    left_values = array("f")
    right_values = array("f")
    left_values.frombytes(left)
    right_values.frombytes(right)
    score = sum(a * b for a, b in zip(left_values, right_values, strict=True))
    return max(-1.0, min(1.0, float(score)))


__all__ = ["VECTOR_DIMENSIONS", "embed_text", "similarity"]
