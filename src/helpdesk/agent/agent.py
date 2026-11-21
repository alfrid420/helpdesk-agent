"""Orchestrator: input guard -> planner LLM -> [MCP tools | policy RAG] -> output guard.

Tool-calling with small local models (Ollama):
  The LLM picks a tool (via TOOL:/ARGS: text format parsed in ollama_client.py).
  We call that tool, then pass the result back and ask the LLM for a plain-text summary.
  The summary call has tools=None so retrieved data can never trigger further tool calls.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from ..guardrails import AuditLog, DisclosureContext, InputGuard, OutputGuard, ToolGuard
from ..guardrails.tool_guard import POLICY_TOOL
from ..llm.base import LLMClient, Message, ToolResult, ToolSpec
from ..rag.answerer import PolicyAnswer
from .mcp_client import McpToolClient
from .prompts import PLANNER_SYSTEM, REFUSAL

MAX_ROUNDS = 4
HISTORY_TURNS = 6

SEARCH_POLICIES_SPEC = ToolSpec(
    name=POLICY_TOOL,
    description=(
        "Search HR/IT policy documents (leave, remote work, expenses, security, onboarding). "
        "Use for ANY question about company policy, rules, benefits or procedures."
    ),
    input_schema={
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
        "additionalProperties": False,
    },
)


class PolicyService:
    async def answer(self, question: str) -> PolicyAnswer: ...  # type: ignore[return]


@dataclass
class ToolTrace:
    name: str
    arguments: dict[str, Any]
    outcome: str
    withheld: list[str] = field(default_factory=list)


@dataclass
class AgentReply:
    text: str
    outcome: str
    route: str
    tools: list[ToolTrace] = field(default_factory=list)
    redactions: dict[str, int] = field(default_factory=dict)
    block_category: str | None = None
    block_reason: str | None = None


class HelpdeskAgent:
    def __init__(
        self,
        *,
        requester_id: str,
        llm: LLMClient,
        tools: McpToolClient,
        policy: PolicyService,
        input_guard: InputGuard,
        output_guard: OutputGuard,
        tool_guard: ToolGuard,
        audit: AuditLog,
    ) -> None:
        self._requester = requester_id
        self._llm = llm
        self._tools = tools
        self._policy = policy
        self._input = input_guard
        self._output = output_guard
        self._tool_guard = tool_guard
        self._audit = audit
        self._history: list[Message] = []
        self._specs: list[ToolSpec] | None = None

    async def _tool_specs(self) -> list[ToolSpec]:
        if self._specs is None:
            self._specs = (
                self._tool_guard.filter_specs(await self._tools.list_tools())
                + [SEARCH_POLICIES_SPEC]
            )
        return self._specs

    async def ask(self, message: str) -> AgentReply:
        # 1. Input guard — blocks injection/jailbreak before the model sees anything
        verdict = await self._input.check(message)
        if not verdict.allowed:
            self._audit.log(
                layer="input_guard",
                category=verdict.category or "unknown",
                reason=verdict.reason or "",
                requester_id=self._requester,
                excerpt=message,
            )
            return AgentReply(
                REFUSAL, "blocked_input", "blocked",
                block_category=verdict.category, block_reason=verdict.reason,
            )

        ctx = DisclosureContext(self._requester)
        for tid in re.findall(r"\bE\d{3}\b", message, re.I):
            ctx.allow(tid.upper())

        specs = await self._tool_specs()
        system = PLANNER_SYSTEM.format(requester_id=self._requester)
        messages = [*self._history, Message("user", text=message)]
        traces: list[ToolTrace] = []

        for _ in range(MAX_ROUNDS):
            # Step A: ask LLM what to do
            resp = await self._llm.complete(system, messages, tools=specs)

            # No tool call → direct answer
            if not resp.tool_calls:
                final = resp.text or REFUSAL
                return self._finish(message, final, ctx, "direct", "allowed", traces)

            # Policy RAG path
            pcall = next((c for c in resp.tool_calls if c.name == POLICY_TOOL), None)
            if pcall:
                tcheck = self._tool_guard.validate_call(pcall.name, pcall.arguments)
                if tcheck.ok:
                    answer = await self._policy.answer(
                        str(pcall.arguments.get("question", message))
                    )
                    traces.append(
                        ToolTrace(POLICY_TOOL, pcall.arguments,
                                  "ok" if answer.covered else "not_covered")
                    )
                    return self._finish(
                        message, answer.text, ctx, "policy_rag",
                        "allowed" if answer.covered else "not_covered", traces,
                    )
                self._tool_guard.log_rejected_call(pcall.name, pcall.arguments, tcheck.reason)
                return self._finish(message, REFUSAL, ctx, "blocked", "blocked_tool", traces)

            # Employee-data path: call each MCP tool, collect results
            tool_results_text: list[str] = []
            for call in resp.tool_calls:
                check = self._tool_guard.validate_call(call.name, call.arguments)
                if not check.ok:
                    self._tool_guard.log_rejected_call(call.name, call.arguments, check.reason)
                    traces.append(ToolTrace(call.name, call.arguments, "rejected_by_guard"))
                    tool_results_text.append(
                        f"Tool {call.name} was rejected: {check.reason}"
                    )
                    continue
                # Real MCP call — goes through the real server over stdio
                data = await self._tools.call_tool(call.name, call.arguments)
                if data.get("ok"):
                    ctx.allow_tool_result(data)
                    traces.append(
                        ToolTrace(call.name, call.arguments, "ok",
                                  list(data.get("withheld_fields", [])))
                    )
                else:
                    traces.append(
                        ToolTrace(call.name, call.arguments,
                                  str(data.get("error", "tool_error")))
                    )
                tool_results_text.append(
                    f"Tool {call.name} result:\n{json.dumps(data, indent=2)}"
                )

            # Step B: summarise tool results in plain English (tools=None → can't chain)
            combined = "\n\n".join(tool_results_text)
            followup = messages + [
                Message("assistant", text=resp.text),
                Message("user", text=(
                    f"Here are the tool results:\n{combined}\n\n"
                    "Now answer the user's original question in plain English. "
                    "Do not output JSON or call any more tools."
                )),
            ]
            summary = await self._llm.complete(system, followup, tools=None)
            return self._finish(
                message, summary.text or REFUSAL, ctx, "employee_data", None, traces
            )

        return self._finish(message, REFUSAL, ctx, "direct", "allowed", traces)

    def _finish(
        self,
        user_message: str,
        text: str,
        ctx: DisclosureContext,
        route: str,
        outcome: str | None,
        traces: list[ToolTrace],
    ) -> AgentReply:
        redacted = self._output.redact(text, ctx)
        if outcome is None:
            ok = [t for t in traces if t.outcome == "ok"]
            denied = [t for t in traces if t.outcome in
                      ("forbidden", "rejected_by_guard", "invalid_employee_id")]
            if denied and not ok:
                outcome = "blocked_tool"
            elif denied or any(t.withheld for t in ok):
                outcome = "partial"
            else:
                outcome = "allowed"
        self._history += [
            Message("user", text=user_message),
            Message("assistant", text=redacted.text),
        ]
        self._history = self._history[-2 * HISTORY_TURNS:]
        return AgentReply(redacted.text, outcome, route, traces, redacted.redactions)
