from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from .embeddings import Embedder
from .models import RetrievedChunk

if TYPE_CHECKING:
    from .store import PgVectorStore


class ChunkRetriever(Protocol):
    def retrieve(self, question: str) -> list[RetrievedChunk]: ...


class Retriever:
    """Top-k vector search, then drop anything below a similarity floor so weak matches never
    reach the LLM at all (the first of two 'refuse when not covered' defences)."""

    def __init__(self, store: "PgVectorStore", embedder: Embedder, k: int = 4, min_similarity: float = 0.5) -> None:
        self._store = store
        self._embedder = embedder
        self._k = k
        self._min = min_similarity

    def retrieve(self, question: str) -> list[RetrievedChunk]:
        hits = self._store.search(self._embedder.embed_query(question), self._k)
        return [h for h in hits if h.similarity >= self._min]
