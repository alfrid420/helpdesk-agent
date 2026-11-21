"""The MCP server (official Python SDK, stdio transport).

One server process is spawned per chat session by the agent's MCP client. The requester identity
arrives via the HELPDESK_REQUESTER_ID environment variable of THAT process, set by the trusted
host application, so the model has no parameter, prompt or tool argument through which it could
change who it is acting as. It only chooses `employee_id`; authorization is decided in tools.py.

Exposes exactly three read-only, allowlisted tools. There is no tool that takes SQL.
Connects to Postgres with the SELECT-only role.
"""
from __future__ import annotations

import json
import os
import sys

from mcp.server.fastmcp import FastMCP

from ..db.repository import EmployeeRepository, PostgresRepository
from ..guardrails.audit_log import AuditLog
from .tools import EmployeeTools


def build_server(repo: EmployeeRepository, requester_id: str, audit: AuditLog) -> FastMCP:
    tools = EmployeeTools(repo, requester_id, audit)
    server = FastMCP("helpdesk-employee-data")

    @server.tool()
    def get_leave_balance(employee_id: str) -> str:
        """Get leave balances (annual, sick, personal) for one employee id such as 'E003'.
        Only allowed for the requester themself or their direct reports."""
        return json.dumps(tools.get_leave_balance(employee_id))

    @server.tool()
    def get_leave_history(employee_id: str) -> str:
        """Get recent leave requests (most recent first) for one employee id such as 'E003'.
        Only allowed for the requester themself or their direct reports."""
        return json.dumps(tools.get_leave_history(employee_id))

    @server.tool()
    def get_employee_profile(employee_id: str) -> str:
        """Get the profile (name, title, department, manager, ...) for one employee id such as 'E003'.
        Contact/salary/address fields are returned only for the requester's own record."""
        return json.dumps(tools.get_employee_profile(employee_id))

    return server


def main() -> None:
    # Deliberately NOT using load_settings()/.env: this process only needs what the host passed it.
    requester = os.environ.get("HELPDESK_REQUESTER_ID", "").strip()
    dsn = os.environ.get("READONLY_DATABASE_URL", "").strip()
    if not requester or not dsn:
        sys.exit("HELPDESK_REQUESTER_ID and READONLY_DATABASE_URL must be set by the host process.")
    repo = PostgresRepository(dsn)
    if repo.get_employee(requester) is None:
        sys.exit(f"Unknown requester '{requester}'.")
    audit = AuditLog(os.environ.get("AUDIT_LOG_PATH", "logs/audit.jsonl"))
    build_server(repo, requester, audit).run(transport="stdio")


if __name__ == "__main__":
    main()
