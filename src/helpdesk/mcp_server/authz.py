"""Authorization rule, enforced at the tool layer (never by prompting).

  * SELF           -> everything about your own record
  * DIRECT_REPORT  -> a manager sees a direct report's leave balance/history and BASIC profile
                      (no phone, salary or address). Direct reports only; not skip-levels.
  * DENIED         -> everyone else. Unknown ids look identical to forbidden ones, so the
                      tools can't be used to probe which employee ids exist.
"""
from __future__ import annotations

from enum import Enum

from ..db.repository import EmployeeRepository


class Access(str, Enum):
    SELF = "self"
    DIRECT_REPORT = "direct_report"
    DENIED = "denied"


BASIC_FIELDS = ("employee_id", "name", "email", "title", "department", "manager_id", "manager_name", "hire_date")
SELF_ONLY_FIELDS = ("phone", "salary", "address")


def resolve_access(repo: EmployeeRepository, requester_id: str, target_id: str) -> Access:
    if requester_id == target_id:
        return Access.SELF if repo.get_employee(target_id) else Access.DENIED
    if repo.get_manager_id(target_id) == requester_id:
        return Access.DIRECT_REPORT
    return Access.DENIED
