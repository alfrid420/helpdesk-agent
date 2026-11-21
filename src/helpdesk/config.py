"""Environment-driven settings. Nothing secret lives in the repo; keys come from env / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised for misconfiguration that the user can fix (shown without a traceback)."""


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    anthropic_api_key: str | None
    anthropic_model: str
    database_url: str
    readonly_database_url: str
    embedding_model: str
    rag_top_k: int
    rag_min_similarity: float
    llm_classifier_enabled: bool
    audit_log_path: str
    policies_dir: str
    seed_path: str


def _bool(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def load_settings() -> Settings:
    load_dotenv()
    return Settings(
        llm_provider=os.environ.get("LLM_PROVIDER", "anthropic").strip().lower(),
        anthropic_api_key=(os.environ.get("ANTHROPIC_API_KEY") or "").strip() or None,
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql://helpdesk:helpdesk@localhost:5433/helpdesk"
        ),
        readonly_database_url=os.environ.get(
            "READONLY_DATABASE_URL", "postgresql://helpdesk_ro:helpdesk_ro@localhost:5433/helpdesk"
        ),
        embedding_model=os.environ.get("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
        rag_top_k=int(os.environ.get("RAG_TOP_K", "4")),
        rag_min_similarity=float(os.environ.get("RAG_MIN_SIMILARITY", "0.5")),
        llm_classifier_enabled=_bool("GUARD_LLM_CLASSIFIER", True),
        audit_log_path=os.environ.get("AUDIT_LOG_PATH", "logs/audit.jsonl"),
        policies_dir=os.environ.get("POLICIES_DIR", "data/policies"),
        seed_path=os.environ.get("SEED_PATH", "data/employees.seed.json"),
    )
