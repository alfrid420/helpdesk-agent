from __future__ import annotations

from ..config import Settings
from ..guardrails import AuditLog, InputGuard, LLMInjectionClassifier, OutputGuard, ToolGuard
from ..llm.base import LLMClient
from ..rag.answerer import PolicyAnswerer
from ..rag.embeddings import Embedder, FastEmbedEmbedder
from ..rag.retriever import Retriever
from ..rag.store import PgVectorStore
from .agent import HelpdeskAgent
from .mcp_client import McpToolClient


def build_agent(
    settings: Settings,
    requester_id: str,
    llm: LLMClient,
    tools: McpToolClient,
    embedder: Embedder | None = None,
) -> HelpdeskAgent:
    audit = AuditLog(settings.audit_log_path)
    tool_guard = ToolGuard(audit, requester_id)
    retriever = Retriever(
        PgVectorStore(settings.readonly_database_url),
        embedder or FastEmbedEmbedder(settings.embedding_model),
        k=settings.rag_top_k,
        min_similarity=settings.rag_min_similarity,
    )
    classifier = LLMInjectionClassifier(llm) if settings.llm_classifier_enabled else None
    return HelpdeskAgent(
        requester_id=requester_id,
        llm=llm,
        tools=tools,
        policy=PolicyAnswerer(llm, retriever, tool_guard),
        input_guard=InputGuard(classifier),
        output_guard=OutputGuard(),
        tool_guard=tool_guard,
        audit=audit,
    )
