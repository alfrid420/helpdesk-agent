"""MCP tools through the real protocol: a real MCP server subprocess and the agent's real MCP
client over stdio. Requires the `mcp` package. The Postgres-backed variant is marked `integration`
and auto-skips when the docker-compose database isn't reachable."""
import asyncio
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from helpdesk.agent.mcp_client import McpToolClient  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def client(requester, tmp_path, *, module="tests.fake_mcp_server_main", extra_env=None):
    env = {
        "HELPDESK_REQUESTER_ID": requester,
        "AUDIT_LOG_PATH": str(tmp_path / "audit.jsonl"),
        "PYTHONPATH": os.pathsep.join([str(ROOT / "src"), str(ROOT)]),
        **(extra_env or {}),
    }
    return McpToolClient(sys.executable, ["-m", module], env, cwd=str(ROOT))


async def _session(requester, tmp_path, fn, **kw):
    async with client(requester, tmp_path, **kw) as c:
        return await fn(c)


def run(requester, tmp_path, fn, **kw):
    return asyncio.run(_session(requester, tmp_path, fn, **kw))


def test_server_exposes_exactly_the_three_allowlisted_tools(tmp_path):
    async def go(c):
        return sorted(t.name for t in await c.list_tools())

    assert run("E003", tmp_path, go) == ["get_employee_profile", "get_leave_balance", "get_leave_history"]


def test_own_record_over_mcp(tmp_path):
    async def go(c):
        return await c.call_tool("get_leave_balance", {"employee_id": "E003"}), await c.call_tool(
            "get_employee_profile", {"employee_id": "E003"}
        )

    bal, prof = run("E003", tmp_path, go)
    assert bal["ok"] and next(b for b in bal["balances"] if b["leave_type"] == "annual")["remaining_days"] == 12.5
    assert prof["ok"] and prof["employee"]["manager_name"] == "Daniel Brooks" and "salary" in prof["employee"]


def test_other_employees_record_is_forbidden_over_mcp_and_logged(tmp_path):
    async def go(c):
        return await c.call_tool("get_employee_profile", {"employee_id": "E005"})

    res = run("E003", tmp_path, go)
    assert res["ok"] is False and res["error"] == "forbidden" and "hannah" not in str(res).lower()
    log = (tmp_path / "audit.jsonl").read_text()
    assert "unauthorized_record_access" in log and "mcp_authz" in log


def test_manager_sees_direct_report_with_self_only_fields_withheld(tmp_path):
    async def go(c):
        return await c.call_tool("get_employee_profile", {"employee_id": "E007"}), await c.call_tool(
            "get_leave_history", {"employee_id": "E007"}
        )

    prof, hist = run("E002", tmp_path, go)
    assert prof["ok"] and "salary" not in prof["employee"] and "phone" not in prof["employee"]
    assert hist["ok"] and len(hist["history"]) >= 1


def test_caller_cannot_smuggle_a_different_requester_identity(tmp_path):
    async def go(c):
        return await c.call_tool("get_employee_profile", {"employee_id": "E005", "requester_id": "E001"})

    res = run("E003", tmp_path, go)
    assert res["ok"] is False  # either rejected as bad arguments or forbidden; never served


def test_injection_style_ids_are_rejected(tmp_path):
    async def go(c):
        return await c.call_tool("get_leave_balance", {"employee_id": "E003' OR '1'='1"})

    assert run("E003", tmp_path, go)["error"] == "invalid_employee_id"


# ---- Postgres-backed (docker compose up + make seed) -------------------------------------------

def _db_reachable() -> bool:
    try:
        import psycopg
        from helpdesk.config import load_settings

        with psycopg.connect(load_settings().readonly_database_url, connect_timeout=2) as conn:
            return conn.execute("SELECT count(*) FROM employees").fetchone()[0] >= 10
    except Exception:
        return False


@pytest.mark.integration
def test_real_server_against_real_postgres(tmp_path):
    if not _db_reachable():
        pytest.skip("docker-compose Postgres not up/seeded (run: make up seed)")
    from helpdesk.config import load_settings

    s = load_settings()
    extra = {"READONLY_DATABASE_URL": s.readonly_database_url}

    async def own(c):
        return await c.call_tool("get_leave_balance", {"employee_id": "E003"})

    async def other(c):
        return await c.call_tool("get_employee_profile", {"employee_id": "E005"})

    res = run("E003", tmp_path, own, module="helpdesk.mcp_server.server", extra_env=extra)
    assert res["ok"] and res["balances"]
    res = run("E003", tmp_path, other, module="helpdesk.mcp_server.server", extra_env=extra)
    assert res["error"] == "forbidden"


@pytest.mark.integration
def test_readonly_role_cannot_write(tmp_path):
    if not _db_reachable():
        pytest.skip("docker-compose Postgres not up/seeded (run: make up seed)")
    import psycopg
    from helpdesk.config import load_settings

    with psycopg.connect(load_settings().readonly_database_url, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE employees SET name = 'x'")
