"""Heading-aware markdown chunker. Each chunk keeps its section path so answers can cite it."""
from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*$")


@dataclass(frozen=True)
class Chunk:
    doc: str  # file name, e.g. leave_policy.md
    section: str  # e.g. "Leave Policy › Carry-Over"
    index: int
    content: str

    @property
    def embed_text(self) -> str:
        return f"{self.section}\n{self.content}"


def _split_blocks(body: str, max_chars: int) -> list[str]:
    """Group paragraphs into pieces <= max_chars (a single oversized paragraph is kept whole)."""
    pieces: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", body.strip()):
        para = para.strip()
        if not para:
            continue
        if current and len(current) + len(para) + 2 > max_chars:
            pieces.append(current)
            current = para
        else:
            current = f"{current}\n\n{para}" if current else para
    if current:
        pieces.append(current)
    return pieces


def chunk_markdown(doc: str, text: str, max_chars: int = 900) -> list[Chunk]:
    stack: list[tuple[int, str]] = []
    sections: list[tuple[str, list[str]]] = [("", [])]
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            level, title = len(m.group(1)), m.group(2)
            stack = [(lv, t) for lv, t in stack if lv < level] + [(level, title)]
            sections.append((" › ".join(t for _, t in stack), []))
        else:
            sections[-1][1].append(line)
    chunks: list[Chunk] = []
    for section, lines in sections:
        for piece in _split_blocks("\n".join(lines), max_chars):
            chunks.append(Chunk(doc, section or doc, len(chunks), piece))
    return chunks
