"""Output guard: PII is redacted unless the tool layer authorized that specific value."""
import pytest

from helpdesk.guardrails.output_guard import DisclosureContext, OutputGuard

og = OutputGuard()


def ctx_for_self() -> DisclosureContext:
    c = DisclosureContext("E003")
    c.allow_tool_result(
        {"ok": True, "employee": {"employee_id": "E003", "email": "aisha.khan@acme-helpdesk.example",
                                  "phone": "+1 555-010-1003", "salary": 128000, "manager_id": "E002",
                                  "address": "221 Birch Avenue, Springfield, IL 62703"}}
    )
    return c


def test_authorized_values_pass_through():
    t = ("Email aisha.khan@acme-helpdesk.example, phone +1 555-010-1003, salary $128,000 per year, "
         "manager E002, address 221 Birch Avenue, Springfield, IL 62703.")
    r = og.redact(t, ctx_for_self())
    assert r.text == t and r.count == 0


@pytest.mark.parametrize(
    "text_in,kind,leaked",
    [
        ("Contact her at hannah.lindqvist@acme-helpdesk.example", "EMAIL", "hannah.lindqvist"),
        ("Her phone is +1 555-010-1005", "PHONE", "010-1005"),
        ("Call (555) 123-4567", "PHONE", "123-4567"),
        ("SSN 123-45-6789", "SSN", "123-45-6789"),
        ("Her salary is $142,000", "SALARY", "142,000"),
        ("He earns 118000 a year", "SALARY", "118000"),
        ("Compensation of $98k", "SALARY", "98k"),
        ("She lives at 77 Oak Drive, Springfield, IL 62705", "ADDRESS", "77 Oak Drive"),
        ("Their ID is E005", "EMPLOYEE_ID", "E005"),
    ],
)
def test_unauthorized_pii_is_redacted(text_in, kind, leaked):
    r = og.redact(text_in, ctx_for_self())
    assert leaked not in r.text
    assert f"[REDACTED:{kind}]" in r.text
    assert r.redactions[kind] >= 1


def test_authorization_is_per_value_not_blanket():
    c = ctx_for_self()
    t = "Mine: aisha.khan@acme-helpdesk.example. Hers: hannah.lindqvist@acme-helpdesk.example"
    r = og.redact(t, c)
    assert "aisha.khan@acme-helpdesk.example" in r.text and "hannah" not in r.text


def test_manager_view_withholds_phone_and_salary_even_if_model_invents_them():
    c = DisclosureContext("E002")
    c.allow_tool_result({"ok": True, "employee": {"employee_id": "E007", "name": "Olivia Martin",
                                                  "email": "olivia.martin@acme-helpdesk.example"}})
    r = og.redact("E007: olivia.martin@acme-helpdesk.example, phone +1 555-010-1007, salary $118,000", c)
    assert "olivia.martin@acme-helpdesk.example" in r.text
    assert "010-1007" not in r.text and "118,000" not in r.text


def test_policy_numbers_and_leave_days_are_not_redacted():
    t = ("Client dinners are limited to $75 per person; receipts are required above $25; managers approve up to "
         "$1,000 and purchases above $5,000 need prior approval. You have 12.5 annual days left; leave 2026-03-30 to 2026-04-03.")
    assert og.redact(t, DisclosureContext("E003")).text == t


def test_redaction_is_idempotent():
    once = og.redact("mail hannah.lindqvist@acme-helpdesk.example", DisclosureContext("E003")).text
    assert og.redact(once, DisclosureContext("E003")).text == once


def test_user_typed_id_can_be_echoed_when_allowed():
    c = DisclosureContext("E003")
    c.allow("E005")
    assert og.redact("I can't share details for E005.", c).text == "I can't share details for E005."
