"""Test doubles. NOTE: the MCP server and its tools are never faked; only the *data backend*
(in-memory instead of Postgres) and the LLM are substituted."""
from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from helpdesk.db.models import Employee, LeaveBalance, LeaveEntry
from helpdesk.llm.base import LLMResponse, Message, ToolCall, ToolSpec

SEED = Path(__file__).resolve().parent.parent / "data" / "employees.seed.json"


class InMemoryRepository:
    """Same interface as PostgresRepository, loaded from the same seed file."""

    def __init__(self) -> None:
        data = json.loads(SEED.read_text(encoding="utf-8"))["employees"]
        names = {e["employee_id"]: e["name"] for e in data}
        self._emp = {
            e["employee_id"]: Employee(
                e["employee_id"], e["name"], e["email"], e["title"], e["department"], e["manager_id"],
                names.get(e["manager_id"]), date.fromisoformat(e["hire_date"]), e["phone"],
                Decimal(str(e["salary"])), e["address"],
            )
            for e in data
        }
        self._bal = {
            e["employee_id"]: [
                LeaveBalance(b["leave_type"], Decimal(str(b["entitlement_days"])), Decimal(str(b["used_days"])))
                for b in e["leave_balances"]
            ]
            for e in data
        }
        self._hist = {
            e["employee_id"]: sorted(
                (
                    LeaveEntry(h["leave_type"], date.fromisoformat(h["start_date"]),
                               date.fromisoformat(h["end_date"]), Decimal(str(h["days"])), h["status"])
                    for h in e["leave_history"]
                ),
                key=lambda x: x.start_date, reverse=True,
            )
            for e in data
        }

    def get_employee(self, employee_id: str) -> Employee | None:
        return self._emp.get(employee_id)

    def get_manager_id(self, employee_id: str) -> str | None:
        e = self._emp.get(employee_id)
        return e.manager_id if e else None

    def get_leave_balances(self, employee_id: str) -> list[LeaveBalance]:
        return list(self._bal.get(employee_id, []))

    def get_leave_history(self, employee_id: str, limit: int = 20) -> list[LeaveEntry]:
        return self._hist.get(employee_id, [])[:limit]


class ScriptedLLM:
    """LLM double: `script` is called with (system, messages, tools) and returns an LLMResponse."""

    def __init__(self, script: Callable[[str, list[Message], list[ToolSpec] | None], LLMResponse]) -> None:
        self._script = script
        self.calls = 0
        self.last_system = ""
        self.last_messages: list[Message] = []

    async def complete(self, system, messages, tools=None, max_tokens=1024) -> LLMResponse:
        self.calls += 1
        self.last_system, self.last_messages = system, list(messages)
        return self._script(system, messages, tools)


def tool_call(name: str, **args: Any) -> LLMResponse:
    return LLMResponse("", [ToolCall(id=f"call_{name}", name=name, arguments=args)])


def text(s: str) -> LLMResponse:
    return LLMResponse(s)


class DirectToolClient:
    """ToolClient double that calls EmployeeTools in-process. Used ONLY for agent-orchestration
    unit tests; the real MCP round trip is covered in test_mcp_tools.py."""

    def __init__(self, tools: Any, specs: list[ToolSpec] | None = None) -> None:
        self._tools = tools
        self._specs = specs or [
            ToolSpec(n, n, {"type": "object"}) for n in ("get_leave_balance", "get_leave_history", "get_employee_profile")
        ]
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[ToolSpec]:
        return self._specs

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        return getattr(self._tools, name)(**arguments)
