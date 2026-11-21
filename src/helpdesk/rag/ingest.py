"""Chunk -> embed -> store. Run: python -m helpdesk.rag.ingest

Documents are stored verbatim (including the deliberately planted injection fixture in
security_policy.md). Sanitization happens at retrieval time, which is what the demo exercises.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..config import load_settings
from .chunker import Chunk, chunk_markdown
from .embeddings import Embedder, FastEmbedEmbedder
from .store import PgVectorStore


def load_chunks(policies_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(policies_dir.glob("*.md")):
        chunks.extend(chunk_markdown(path.name, path.read_text(encoding="utf-8")))
    return chunks


def ingest(policies_dir: Path, store: PgVectorStore, embedder: Embedder) -> int:
    chunks = load_chunks(policies_dir)
    if not chunks:
        raise SystemExit(f"No .md policy files found in {policies_dir}")
    vectors = embedder.embed_documents([c.embed_text for c in chunks])
    store.replace_all(list(zip(chunks, vectors)))
    return len(chunks)


def main() -> None:
    import psycopg

    s = load_settings()
    try:
        n = ingest(Path(s.policies_dir), PgVectorStore(s.database_url), FastEmbedEmbedder(s.embedding_model))
    except psycopg.OperationalError as exc:
        sys.exit(f"Could not connect to Postgres ({exc}). Is it running? Try: make up")
    print(f"Ingested {n} chunks from {s.policies_dir}.")


if __name__ == "__main__":
    main()
