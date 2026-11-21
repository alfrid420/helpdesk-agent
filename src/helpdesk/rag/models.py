from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievedChunk:
    doc: str
    section: str
    chunk_index: int
    content: str
    similarity: float
