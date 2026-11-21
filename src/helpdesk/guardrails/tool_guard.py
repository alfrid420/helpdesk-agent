"""Tool guard: nothing the user types or the documents say can reach a tool unless it passes here.

* Only allowlisted tools are ever shown to the model (`filter_specs`).
* Every tool call the model emits is validated against a strict schema (`validate_call`).
* Retrieved document text is untrusted: instruction-like content is stripped and logged
  (`sanitize_retrieved`) and what remains is wrapped as quoted data (`wrap_untrusted`).
  Structurally, the LLM call that reads retrieved text is also given NO tools at all.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from ..llm.base import ToolSpec
from .audit_log import AuditLog
from .patterns import scan

MCP_TOOL_ALLOWLIST = frozenset({"get_leave_balance", "get_leave_history", "get_employee_profile"})
POLICY_TOOL = "search_policies"
EMPLOYEE_ID_RE = re.compile(r"E\d{3}")  # use fullmatch ($ would accept a trailing newline)
MAX_QUESTION_CHARS = 500

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
REMOVED_MARKER = "[removed: instruction-like content in retrieved document]"


@dataclass(frozen=True)
class ToolVerdict:
    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class SanitizedText:
    text: str
    removed: list[str] = field(default_factory=list)


class ToolGuard:
    def __init__(self, audit: AuditLog, requester_id: str | None = None) -> None:
        self._audit = audit
        self._requester = requester_id

    def filter_specs(self, specs: list[ToolSpec]) -> list[ToolSpec]:
        return [s for s in specs if s.name in MCP_TOOL_ALLOWLIST]

    def validate_call(self, name: str, arguments: dict[str, object]) -> ToolVerdict:
        if name == POLICY_TOOL:
            q = arguments.get("question")
            if set(arguments) != {"question"} or not isinstance(q, str) or not q.strip():
                return ToolVerdict(False, "search_policies requires exactly one non-empty 'question' string")
            if len(q) > MAX_QUESTION_CHARS:
                return ToolVerdict(False, "question too long")
            return ToolVerdict(True)
        if name not in MCP_TOOL_ALLOWLIST:
            return ToolVerdict(False, f"tool '{name}' is not on the allowlist")
        emp = arguments.get("employee_id")
        if set(arguments) != {"employee_id"}:
            return ToolVerdict(False, "unexpected or missing arguments; only 'employee_id' is accepted")
        if not isinstance(emp, str) or not EMPLOYEE_ID_RE.fullmatch(emp):
            return ToolVerdict(False, "employee_id must match E followed by 3 digits")
        return ToolVerdict(True)

    def log_rejected_call(self, name: str, arguments: dict[str, object], reason: str) -> None:
        self._audit.log(
            layer="tool_guard",
            category="invalid_tool_call",
            reason=reason,
            requester_id=self._requester,
            excerpt=f"{name}({arguments})",
        )

    def sanitize_retrieved(self, doc: str, section: str, text: str) -> SanitizedText:
        """Strip HTML comments and any line that looks like an instruction to the AI. Log hits."""
        removed: list[str] = []

        def handle_comment(m: re.Match[str]) -> str:
            if scan(m.group(0)):
                removed.append(m.group(0))
                return REMOVED_MARKER
            return ""  # harmless comments are simply dropped; the model never needs them

        text = _COMMENT_RE.sub(handle_comment, text)
        clean_lines: list[str] = []
        for line in text.splitlines():
            if line.strip() != REMOVED_MARKER and scan(line):
                removed.append(line)
                clean_lines.append(REMOVED_MARKER)
            else:
                clean_lines.append(line)
        for frag in removed:
            findings = scan(frag)
            self._audit.log(
                layer="rag_sanitizer",
                category="indirect_prompt_injection",
                reason=f"retrieved text from {doc} › {section} contained instruction-like content: "
                + "; ".join(f.rule for f in findings[:3]),
                requester_id=self._requester,
                excerpt=frag,
                extra={"doc": doc, "section": section},
            )
        return SanitizedText("\n".join(clean_lines).strip(), removed)

    @staticmethod
    def wrap_untrusted(index: int, doc: str, section: str, text: str) -> str:
        """Quote retrieved text as inert data (angle brackets escaped so it can't fake tags)."""
        return (
            f'<doc id="{index}" source="{html.escape(doc)}" section="{html.escape(section)}">\n'
            f"{html.escape(text, quote=False)}\n</doc>"
        )
