"""Append-only JSONL log of every blocked attempt (input guard, tool guard, MCP authorization)."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()


class AuditLog:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def log(
        self,
        *,
        layer: str,
        category: str,
        reason: str,
        requester_id: str | None,
        excerpt: str = "",
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "event": "blocked",
            "layer": layer,  # input_guard | tool_guard | mcp_authz | rag_sanitizer
            "category": category,
            "reason": reason,
            "requester_id": requester_id,
            "excerpt": excerpt[:200],
            "excerpt_sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest()[:16],
        }
        if extra:
            entry["extra"] = extra
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with _lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
