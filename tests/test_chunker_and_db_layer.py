import inspect
from pathlib import Path

from helpdesk.db.repository import EmployeeRepository, PostgresRepository
from helpdesk.rag.chunker import chunk_markdown
from helpdesk.rag.ingest import load_chunks

POLICIES = Path(__file__).resolve().parent.parent / "data" / "policies"


def test_chunks_carry_section_paths():
    chunks = chunk_markdown("leave_policy.md", (POLICIES / "leave_policy.md").read_text())
    sections = {c.section for c in chunks}
    assert "Leave Policy › Carry-Over" in sections and "Leave Policy › Annual Leave" in sections
    carry = next(c for c in chunks if c.section.endswith("Carry-Over"))
    assert "5 unused annual leave days" in carry.content


def test_long_sections_are_split_but_never_empty():
    body = "\n\n".join(f"Paragraph {i} " + "word " * 60 for i in range(10))
    chunks = chunk_markdown("d.md", f"# T\n\n## S\n\n{body}", max_chars=500)
    assert len(chunks) > 3 and all(c.content.strip() for c in chunks)
    assert [c.index for c in chunks] == list(range(len(chunks)))


def test_all_five_policies_ingest_and_fixture_is_stored_verbatim():
    chunks = load_chunks(POLICIES)
    assert {c.doc for c in chunks} == {
        "leave_policy.md", "remote_work_policy.md", "expenses_policy.md", "security_policy.md", "onboarding_guide.md"
    }
    # The planted injection is stored raw at ingest; it is neutralised at retrieval time.
    assert any("TEST FIXTURE" in c.content for c in chunks if c.doc == "security_policy.md")


def test_repository_api_never_accepts_sql_or_query_strings():
    forbidden_params = {"sql", "query", "statement", "where", "raw", "clause", "command"}
    for cls in (PostgresRepository, EmployeeRepository):
        for name, fn in inspect.getmembers(cls, inspect.isfunction):
            if name.startswith("_"):
                continue
            assert not forbidden_params & set(inspect.signature(fn).parameters), f"{cls.__name__}.{name}"
            assert not name.startswith(("execute", "run", "raw", "query", "sql"))


def test_every_sql_statement_is_a_constant_with_bound_parameters():
    from helpdesk.db import repository

    stmts = [v for k, v in vars(repository).items() if k.endswith("_SQL")]
    assert stmts and all("%s" in s for s in stmts)
    assert not any("{" in s or "'" in s for s in stmts)  # no f-string / inlined literals
