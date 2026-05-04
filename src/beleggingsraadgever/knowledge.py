"""Local document chunking and vector search primitives."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, List

from .models import KnowledgeChunk

TOKEN_RE = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_\-.]{1,}")


def tokenize(text: str) -> List[str]:
    return [match.group(0).lower() for match in TOKEN_RE.finditer(text)]


def chunk_text(
    text: str,
    document_id: int,
    max_chars: int = 1200,
    overlap: int = 150,
    tags: Iterable[str] = (),
) -> List[KnowledgeChunk]:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []

    chunks: List[KnowledgeChunk] = []
    start = 0
    chunk_index = 0
    tag_list = list(tags)

    while start < len(cleaned):
        end = min(start + max_chars, len(cleaned))
        if end < len(cleaned):
            sentence_end = cleaned.rfind(". ", start, end)
            if sentence_end > start + max_chars // 2:
                end = sentence_end + 1

        chunk_body = cleaned[start:end].strip()
        if chunk_body:
            chunks.append(
                KnowledgeChunk(
                    document_id=document_id,
                    chunk_index=chunk_index,
                    text=chunk_body,
                    tags=tag_list,
                )
            )
            chunk_index += 1

        if end >= len(cleaned):
            break
        start = max(0, end - overlap)

    return chunks


class HashingVectorizer:
    """Small deterministic vectorizer for a dependency-free first RAG layer."""

    def __init__(self, dimensions: int = 384) -> None:
        self.dimensions = dimensions

    def vectorize(self, text: str) -> List[float]:
        vector = [0.0] * self.dimensions
        tokens = tokenize(text)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            number = int.from_bytes(digest, "big")
            index = number % self.dimensions
            sign = 1.0 if number & 1 else -1.0
            vector[index] += sign

        return _l2_normalize(vector)


def cosine_similarity(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def _l2_normalize(vector: List[float]) -> List[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]

