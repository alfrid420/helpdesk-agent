"""Entry point: the REAL MCP server (build_server over stdio) backed by the in-memory repository,
so the MCP protocol round trip can be tested without Postgres. Run as: python -m tests.fake_mcp_server_main"""
import os

from helpdesk.guardrails.audit_log import AuditLog
from helpdesk.mcp_server.server import build_server
from tests.fakes import InMemoryRepository

if __name__ == "__main__":
    build_server(InMemoryRepository(), os.environ["HELPDESK_REQUESTER_ID"], AuditLog(os.environ["AUDIT_LOG_PATH"])).run(
        transport="stdio"
    )
