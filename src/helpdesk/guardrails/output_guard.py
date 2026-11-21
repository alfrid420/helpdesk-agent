"""Output guard: redact PII in the final reply unless the requester is authorized for it.

"Authorized" is decided by the tool layer, not here: only values that an MCP tool actually
returned to this requester (the tool already applied the self / direct-report rule) are allowed
through. Anything PII-shaped that is NOT among those values, whether hallucinated, remembered,
or smuggled in by an injection, is redacted.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

_MONEY = (
    r"(?:[$€£₹]\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:[kK]\b|lakhs?\b|million\b))?"
    r"|\b\d{2,3}[kK]\b|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d{5,7}(?:\.\d+)?\b)"
)
_SALARY_WORDS = (
    r"(?:salary|salaries|compensation|remuneration|wages?|ctc|earns?|earning|"
    r"base pay|annual pay|monthly pay|gross pay|net pay|take-home pay)"
)

# (kind, regex, group-to-redact). Order matters: SSN before phone, etc.
_PATTERNS: list[tuple[str, re.Pattern[str], str | int]] = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), 0),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), 0),
    ("PHONE", re.compile(r"(?<![\w/])(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"), 0),
    ("SALARY", re.compile(rf"\b{_SALARY_WORDS}\b[^.\n]{{0,50}}?(?P<amt>{_MONEY})", re.I), "amt"),
    ("SALARY", re.compile(rf"(?P<amt>{_MONEY})\s?(?:/|per |a |each )?\s?(?:year|yr|annum|annually)\b", re.I), "amt"),
    (
        "ADDRESS",
        re.compile(
            r"\b\d{1,5}\s+(?:[A-Za-z]+\s+){1,3}(?:street|st|avenue|ave|road|rd|lane|ln|drive|dr|"
            r"boulevard|blvd|way|court|ct|place|pl)\b\.?(?:,?\s+[A-Za-z .]+,?\s+[A-Z]{2}\s+\d{5})?",
            re.I,
        ),
        0,
    ),
    ("EMPLOYEE_ID", re.compile(r"\bE\d{3}\b", re.I), 0),
]


def canon(value: Any) -> str:
    """Canonical form for comparing values regardless of formatting ('$98,000' == 98000)."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


@dataclass
class DisclosureContext:
    """What this requester has been authorized to see in this turn."""

    requester_id: str
    allowed: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.allow(self.requester_id)

    def allow(self, value: Any) -> None:
        c = canon(value)
        if not c:
            return
        self.allowed.add(c)
        if c.isdigit() and len(c) >= 4 and c.endswith("000"):
            self.allowed.add(f"{int(c) // 1000}k")  # "$98k" for 98000

    def allow_tool_result(self, result: Any) -> None:
        """Allow every leaf value of a *successful* tool result (the tool already filtered it)."""
        if isinstance(result, dict):
            for v in result.values():
                self.allow_tool_result(v)
        elif isinstance(result, list):
            for v in result:
                self.allow_tool_result(v)
        elif result is not None and not isinstance(result, bool):
            self.allow(result)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    redactions: dict[str, int]

    @property
    def count(self) -> int:
        return sum(self.redactions.values())


class OutputGuard:
    def redact(self, text: str, ctx: DisclosureContext) -> RedactionResult:
        counts: Counter[str] = Counter()
        for kind, rx, group in _PATTERNS:

            def repl(m: re.Match[str], kind: str = kind, group: str | int = group) -> str:
                target = m.group(group)
                if canon(target) in ctx.allowed:
                    return m.group(0)
                counts[kind] += 1
                if group == 0:
                    return f"[REDACTED:{kind}]"
                start, end = m.span(group)
                base = m.start(0)
                s = m.group(0)
                return f"{s[: start - base]}[REDACTED:{kind}]{s[end - base:]}"

            text = rx.sub(repl, text)
        return RedactionResult(text, dict(counts))
