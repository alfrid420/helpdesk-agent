"""Authorization is enforced in the tool layer: self, or a manager viewing direct reports."""
import pytest

from helpdesk.guardrails.audit_log import AuditLog
from helpdesk.mcp_server.authz import Access, resolve_access
from helpdesk.mcp_server.tools import FORBIDDEN_MESSAGE, EmployeeTools
from tests.fakes import InMemoryRepository


@pytest.fixture()
def repo():
    return InMemoryRepository()


def tools_for(repo, requester, tmp_path):
    return EmployeeTools(repo, requester, AuditLog(tmp_path / "audit.jsonl")), AuditLog(tmp_path / "audit.jsonl")


def test_access_levels(repo):
    assert resolve_access(repo, "E003", "E003") is Access.SELF
    assert resolve_access(repo, "E002", "E007") is Access.DIRECT_REPORT
    assert resolve_access(repo, "E003", "E005") is Access.DENIED  # unrelated
    assert resolve_access(repo, "E003", "E004") is Access.DENIED  # peer
    assert resolve_access(repo, "E003", "E002") is Access.DENIED  # employee -> their own manager
    assert resolve_access(repo, "E001", "E003") is Access.DENIED  # skip-level is NOT a direct report
    assert resolve_access(repo, "E003", "E999") is Access.DENIED  # unknown


def test_self_sees_everything(repo, tmp_path):
    t, _ = tools_for(repo, "E003", tmp_path)
    res = t.get_employee_profile("E003")
    assert res["ok"] and res["access"] == "self" and res["withheld_fields"] == []
    assert {"phone", "salary", "address"} <= set(res["employee"])
    assert res["employee"]["manager_name"] == "Daniel Brooks"
    bal = t.get_leave_balance("E003")
    annual = next(b for b in bal["balances"] if b["leave_type"] == "annual")
    assert annual["remaining_days"] == 12.5


def test_manager_sees_direct_report_but_not_self_only_fields(repo, tmp_path):
    t, _ = tools_for(repo, "E002", tmp_path)
    prof = t.get_employee_profile("E007")
    assert prof["ok"] and prof["access"] == "direct_report"
    assert not {"phone", "salary", "address"} & set(prof["employee"])
    assert set(prof["withheld_fields"]) == {"phone", "salary", "address"}
    assert t.get_leave_history("E007")["ok"] and t.get_leave_balance("E007")["ok"]


@pytest.mark.parametrize("tool", ["get_leave_balance", "get_leave_history", "get_employee_profile"])
@pytest.mark.parametrize("requester,target", [("E003", "E005"), ("E003", "E004"), ("E001", "E003"), ("E003", "E999")])
def test_forbidden_everywhere_and_indistinguishable_from_unknown(repo, tmp_path, tool, requester, target):
    t, audit = tools_for(repo, requester, tmp_path)
    res = getattr(t, tool)(target)
    assert res == {"ok": False, "error": "forbidden", "message": FORBIDDEN_MESSAGE}
    assert "email" not in str(res) and "salary" not in str(res)
    entry = audit.read()[-1]
    assert entry["layer"] == "mcp_authz" and entry["category"] == "unauthorized_record_access"


@pytest.mark.parametrize("bad", ["E5", "e003", "E003; DROP TABLE employees", "' OR '1'='1", "", "E0031", "E003\n"])
def test_malformed_ids_are_rejected_before_any_lookup(repo, tmp_path, bad):
    t, _ = tools_for(repo, "E003", tmp_path)
    assert t.get_employee_profile(bad)["error"] == "invalid_employee_id"


def test_requester_identity_cannot_be_changed_by_the_caller(repo, tmp_path):
    t, _ = tools_for(repo, "E003", tmp_path)
    with pytest.raises(TypeError):
        t.get_employee_profile("E005", requester_id="E001")  # type: ignore[call-arg]
