"""Semantic recall protocols and an offline, deterministic stub implementation.

`Embedder` and `SemanticIndex` are the interfaces a real (online) vector store
would implement (e.g. a sentence-transformers embedder backed by chromadb).
This module ships neither of those -- only `StubEmbedder` and `InMemoryIndex`,
which are fully offline, deterministic, and dependency-free. They exist so the
rest of the codebase and its tests can depend on the protocols without ever
needing network access or a real embedding model.
"""

import hashlib
import math
import uuid
from typing import Protocol

_VECTOR_DIM = 64


class Embedder(Protocol):
    """Turns text into fixed-length vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SemanticIndex(Protocol):
    """Stores (text, metadata) pairs and answers nearest-neighbor queries."""

    def add(self, items: list[tuple[str, dict]]) -> None: ...

    def query(self, text: str, k: int) -> list[dict]:
        """Return the stored metadata dicts of the `k` nearest items."""
        ...


class StubEmbedder:
    """Deterministic, offline bag-of-tokens embedder.

    Each token is hashed into one of `_VECTOR_DIM` buckets and accumulated
    into that bucket; the resulting vector is L2-normalized. This is not a
    real embedding model -- it has no notion of meaning -- but it is stable
    (same text -> same vector, no downloads, no randomness) and it gives
    texts that share tokens a higher cosine similarity than texts that don't,
    which is enough structure for offline tests and local dev to exercise
    nearest-neighbor recall without a network dependency.
    """

    def __init__(self, dim: int = _VECTOR_DIM) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            return vector
        return [v / norm for v in vector]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class InMemoryIndex:
    """Pure-Python `SemanticIndex` that keeps every vector in a list.

    Nearest neighbors are found by exact cosine similarity, computed without
    numpy. This is the offline default: fine for the small in-process
    corpora used in tests and local dev, not intended to scale to a large
    persistent index (that's what a real chromadb-backed index, added in a
    later task, is for).
    """

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._items: list[tuple[list[float], dict]] = []

    def add(self, items: list[tuple[str, dict]]) -> None:
        if not items:
            return
        texts = [text for text, _ in items]
        vectors = self._embedder.embed(texts)
        for vector, (_, metadata) in zip(vectors, items, strict=True):
            self._items.append((vector, metadata))

    def query(self, text: str, k: int) -> list[dict]:
        if not self._items or k <= 0:
            return []
        (query_vector,) = self._embedder.embed([text])
        scored = [
            (_cosine_similarity(query_vector, vector), metadata)
            for vector, metadata in self._items
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [metadata for _, metadata in scored[:k]]


class ChromaIndex:
    """`SemanticIndex` backed by a (persistent or in-memory) chromadb collection.

    `chromadb` is a large optional dependency (the `semantic` extra), so it
    is imported lazily -- inside `__init__`, never at module top level. That
    keeps `import asc_metadata_verifier.persistence.semantic` (and anything
    that transitively imports this module, including the default/no-extra
    CLI install) free of any chromadb import; only code that actually
    constructs a `ChromaIndex` pays that cost, and it fails with a normal
    `ModuleNotFoundError` at that point if the extra isn't installed.

    Embeddings are always produced by the injected `embedder` and passed to
    chromadb explicitly via `embeddings=`/`query_embeddings=`, never left for
    chromadb's own default embedding function to compute -- so the embedding
    model in use is always the one this codebase chose (e.g. `StubEmbedder`
    for fully offline tests/dev), and chromadb never tries to lazily
    download a default model.
    """

    _COLLECTION_NAME = "asc_metadata_verifier"

    def __init__(self, embedder: Embedder, path: str | None = None) -> None:
        import chromadb

        self._embedder = embedder
        self._client = (
            chromadb.EphemeralClient() if path is None else chromadb.PersistentClient(path=path)
        )
        self._collection = self._client.get_or_create_collection(
            name=self._COLLECTION_NAME, embedding_function=None
        )

    def add(self, items: list[tuple[str, dict]]) -> None:
        if not items:
            return
        texts = [text for text, _ in items]
        vectors = self._embedder.embed(texts)
        self._collection.add(
            ids=[uuid.uuid4().hex for _ in items],
            embeddings=vectors,
            metadatas=[metadata for _, metadata in items],
            documents=texts,
        )

    def query(self, text: str, k: int) -> list[dict]:
        if k <= 0 or self._collection.count() == 0:
            return []
        (query_vector,) = self._embedder.embed([text])
        results = self._collection.query(query_embeddings=[query_vector], n_results=k)
        metadatas = results.get("metadatas") or [[]]
        return list(metadatas[0])
