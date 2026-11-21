"""Load data/employees.seed.json into Postgres (owner role). Run: python -m helpdesk.db.seed"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..config import load_settings

_TRUNCATE = "TRUNCATE leave_history, leave_balances, employees RESTART IDENTITY CASCADE"
_INSERT_EMP = """
    INSERT INTO employees (employee_id, name, email, title, department, manager_id,
                           hire_date, phone, salary, address)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""
_INSERT_BAL = """
    INSERT INTO leave_balances (employee_id, leave_type, entitlement_days, used_days)
    VALUES (%s, %s, %s, %s)
"""
_INSERT_HIST = """
    INSERT INTO leave_history (employee_id, leave_type, start_date, end_date, days, status)
    VALUES (%s, %s, %s, %s, %s, %s)
"""


def seed_database(dsn: str, seed_path: Path) -> int:
    import psycopg

    data = json.loads(seed_path.read_text(encoding="utf-8"))
    with psycopg.connect(dsn) as conn:  # one transaction; FK on manager_id is deferred
        conn.execute(_TRUNCATE)
        for e in data["employees"]:
            conn.execute(
                _INSERT_EMP,
                (e["employee_id"], e["name"], e["email"], e["title"], e["department"],
                 e["manager_id"], e["hire_date"], e["phone"], e["salary"], e["address"]),
            )
            for b in e["leave_balances"]:
                conn.execute(_INSERT_BAL, (e["employee_id"], b["leave_type"], b["entitlement_days"], b["used_days"]))
            for h in e["leave_history"]:
                conn.execute(
                    _INSERT_HIST,
                    (e["employee_id"], h["leave_type"], h["start_date"], h["end_date"], h["days"], h["status"]),
                )
    return len(data["employees"])


def main() -> None:
    import psycopg

    settings = load_settings()
    try:
        n = seed_database(settings.database_url, Path(settings.seed_path))
    except psycopg.OperationalError as exc:
        sys.exit(f"Could not connect to Postgres ({exc}). Is it running? Try: make up")
    print(f"Seeded {n} employees.")


if __name__ == "__main__":
    main()
