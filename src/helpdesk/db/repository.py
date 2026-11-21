"""Data access for employee records.

Design rule: this layer exposes a small, fixed set of typed read methods. There is NO method that
accepts a SQL string (or any query fragment), every statement below is a module-level constant,
and every value reaches Postgres as a bound parameter. The model never gets near SQL.
"""
from __future__ import annotations

from typing import Protocol

from .models import Employee, LeaveBalance, LeaveEntry

_PROFILE_SQL = """
    SELECT e.employee_id, e.name, e.email, e.title, e.department, e.manager_id,
           m.name AS manager_name, e.hire_date, e.phone, e.salary, e.address
    FROM employees e
    LEFT JOIN employees m ON m.employee_id = e.manager_id
    WHERE e.employee_id = %s
"""
_MANAGER_SQL = "SELECT manager_id FROM employees WHERE employee_id = %s"
_EXISTS_SQL = "SELECT 1 FROM employees WHERE employee_id = %s"
_BALANCES_SQL = """
    SELECT leave_type, entitlement_days, used_days
    FROM leave_balances WHERE employee_id = %s ORDER BY leave_type
"""
_HISTORY_SQL = """
    SELECT leave_type, start_date, end_date, days, status
    FROM leave_history WHERE employee_id = %s ORDER BY start_date DESC LIMIT %s
"""


class EmployeeRepository(Protocol):
    """What the MCP tools need. Implemented by Postgres (prod) and an in-memory fake (tests)."""

    def get_employee(self, employee_id: str) -> Employee | None: ...
    def get_manager_id(self, employee_id: str) -> str | None: ...
    def get_leave_balances(self, employee_id: str) -> list[LeaveBalance]: ...
    def get_leave_history(self, employee_id: str, limit: int = 20) -> list[LeaveEntry]: ...


class PostgresRepository:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    def _fetch(self, statement: str, params: tuple[object, ...]) -> list[dict[str, object]]:
        # Private helper: callers pass only the module-level constants above.
        import psycopg  # lazy
        from psycopg.rows import dict_row

        with psycopg.connect(self._dsn, row_factory=dict_row, autocommit=True) as conn:
            return list(conn.execute(statement, params).fetchall())  # type: ignore[arg-type]

    def get_employee(self, employee_id: str) -> Employee | None:
        rows = self._fetch(_PROFILE_SQL, (employee_id,))
        return Employee(**rows[0]) if rows else None  # type: ignore[arg-type]

    def get_manager_id(self, employee_id: str) -> str | None:
        rows = self._fetch(_MANAGER_SQL, (employee_id,))
        return rows[0]["manager_id"] if rows else None  # type: ignore[return-value]

    def get_leave_balances(self, employee_id: str) -> list[LeaveBalance]:
        return [LeaveBalance(**r) for r in self._fetch(_BALANCES_SQL, (employee_id,))]  # type: ignore[arg-type]

    def get_leave_history(self, employee_id: str, limit: int = 20) -> list[LeaveEntry]:
        bounded = max(1, min(int(limit), 50))
        return [LeaveEntry(**r) for r in self._fetch(_HISTORY_SQL, (employee_id, bounded))]  # type: ignore[arg-type]
