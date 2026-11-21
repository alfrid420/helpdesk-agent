from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class Employee:
    employee_id: str
    name: str
    email: str
    title: str
    department: str
    manager_id: str | None
    manager_name: str | None
    hire_date: date
    phone: str | None
    salary: Decimal | None
    address: str | None


@dataclass(frozen=True)
class LeaveBalance:
    leave_type: str
    entitlement_days: Decimal
    used_days: Decimal

    @property
    def remaining_days(self) -> Decimal:
        return self.entitlement_days - self.used_days


@dataclass(frozen=True)
class LeaveEntry:
    leave_type: str
    start_date: date
    end_date: date
    days: Decimal
    status: str
