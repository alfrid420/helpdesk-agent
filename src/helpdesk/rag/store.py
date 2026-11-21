"""pgvector-backed chunk store. Writes use the owner DSN (ingest only); search uses the
read-only DSN. All SQL is constant."""
from __future__ import annotations

from typing import Any

import numpy as np

from .chunker import Chunk
from .models import RetrievedChunk

_CLEAR = "TRUNCATE doc_chunks RESTART IDENTITY"
_INSERT = "INSERT INTO doc_chunks (doc, section, chunk_index, content, embedding) VALUES (%s, %s, %s, %s, %s)"
_SEARCH = """
    SELECT doc, section, chunk_index, content, 1 - (embedding <=> %s) AS similarity
    FROM doc_chunks ORDER BY embedding <=> %s LIMIT %s
"""


class PgVectorStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _connect(self) -> Any:
        import psycopg  # lazy: keeps pure-logic modules importable without the driver
        from pgvector.psycopg import register_vector

        conn = psycopg.connect(self._dsn, autocommit=True)
        register_vector(conn)
        return conn

    def replace_all(self, rows: list[tuple[Chunk, np.ndarray]]) -> None:
        with self._connect() as conn:
            conn.execute(_CLEAR)
            for chunk, vec in rows:
                conn.execute(_INSERT, (chunk.doc, chunk.section, chunk.index, chunk.content, vec))

    def search(self, embedding: np.ndarray, k: int) -> list[RetrievedChunk]:
        from psycopg.rows import dict_row

        with self._connect() as conn:
            conn.row_factory = dict_row
            rows = conn.execute(_SEARCH, (embedding, embedding, max(1, min(k, 20)))).fetchall()
        return [RetrievedChunk(r["doc"], r["section"], r["chunk_index"], r["content"], float(r["similarity"])) for r in rows]
