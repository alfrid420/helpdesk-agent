"""Tool implementations (pure functions over a repository), so authorization can be unit-tested
without MCP or Postgres. server.py is a thin MCP wrapper around these."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from ..db.models import Employee
from ..db.repository import EmployeeRepository
from ..guardrails.audit_log import AuditLog
from .authz import BASIC_FIELDS, SELF_ONLY_FIELDS, Access, resolve_access

_ID_RE = re.compile(r"E\d{3}")  # always used with fullmatch ($ would accept a trailing newline)
FORBIDDEN_MESSAGE = "You are not authorized to view this record, or it does not exist."


def _num(d: Decimal) -> int | float:
    return int(d) if d == d.to_integral_value() else float(d)


def _err(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message}


class EmployeeTools:
    def __init__(self, repo: EmployeeRepository, requester_id: str, audit: AuditLog) -> None:
        self._repo = repo
        self._requester = requester_id  # fixed when the server process starts; never from the model
        self._audit = audit

    def _authorize(self, tool: str, employee_id: str) -> tuple[Access | None, dict[str, Any] | None]:
        if not isinstance(employee_id, str) or not _ID_RE.fullmatch(employee_id):
            return None, _err("invalid_employee_id", "employee_id must look like E003.")
        access = resolve_access(self._repo, self._requester, employee_id)
        if access is Access.DENIED:
            self._audit.log(
                layer="mcp_authz",
                category="unauthorized_record_access",
                reason=f"{self._requester} called {tool}({employee_id}): target is neither self nor a direct report",
                requester_id=self._requester,
                excerpt=f"{tool}({employee_id})",
            )
            return None, _err("forbidden", FORBIDDEN_MESSAGE)
        return access, None

    def get_leave_balance(self, employee_id: str) -> dict[str, Any]:
        access, err = self._authorize("get_leave_balance", employee_id)
        if err or access is None:
            return err or _err("forbidden", FORBIDDEN_MESSAGE)
        balances = self._repo.get_leave_balances(employee_id)
        return {
            "ok": True,
            "employee_id": employee_id,
            "access": access.value,
            "balances": [
                {
                    "leave_type": b.leave_type,
                    "entitlement_days": _num(b.entitlement_days),
                    "used_days": _num(b.used_days),
                    "remaining_days": _num(b.remaining_days),
                }
                for b in balances
            ],
        }

    def get_leave_history(self, employee_id: str) -> dict[str, Any]:
        access, err = self._authorize("get_leave_history", employee_id)
        if err or access is None:
            return err or _err("forbidden", FORBIDDEN_MESSAGE)
        return {
            "ok": True,
            "employee_id": employee_id,
            "access": access.value,
            "history": [
                {
                    "leave_type": h.leave_type,
                    "start_date": h.start_date.isoformat(),
                    "end_date": h.end_date.isoformat(),
                    "days": _num(h.days),
                    "status": h.status,
                }
                for h in self._repo.get_leave_history(employee_id)
            ],
        }

    def get_employee_profile(self, employee_id: str) -> dict[str, Any]:
        access, err = self._authorize("get_employee_profile", employee_id)
        if err or access is None:
            return err or _err("forbidden", FORBIDDEN_MESSAGE)
        emp = self._repo.get_employee(employee_id)
        if emp is None:  # can't happen after authorize, but never trust that
            return _err("forbidden", FORBIDDEN_MESSAGE)
        fields = list(BASIC_FIELDS) + (list(SELF_ONLY_FIELDS) if access is Access.SELF else [])
        profile = {f: _field(emp, f) for f in fields}
        withheld = [] if access is Access.SELF else list(SELF_ONLY_FIELDS)
        return {
            "ok": True,
            "access": access.value,
            "employee": profile,
            "withheld_fields": withheld,
            **({"note": "phone, salary and address are visible only to the employee themself"} if withheld else {}),
        }


def _field(emp: Employee, name: str) -> Any:
    value = getattr(emp, name)
    if isinstance(value, Decimal):
        return _num(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value
