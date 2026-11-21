PY := .venv/bin/python
AS ?= E003

.PHONY: demo chat up down seed ingest test test-all questions clean

# One command: venv + deps + Postgres + seed + ingest + interactive chat (as $(AS), default E003).
demo: seed ingest
	$(PY) -m helpdesk.cli --as $(AS)

chat:
	$(PY) -m helpdesk.cli --as $(AS)

.venv/bin/python:
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -e ".[dev]"

.env:
	cp .env.example .env

up: .env
	docker compose up -d --wait

down:
	docker compose down

seed: .venv/bin/python up
	$(PY) -m helpdesk.db.seed

ingest: .venv/bin/python up
	$(PY) -m helpdesk.rag.ingest

# Unit tests (no Docker needed; integration tests auto-skip).
test: .venv/bin/python
	$(PY) -m pytest -q

# Everything, including MCP-server-against-real-Postgres tests.
test-all: seed
	$(PY) -m pytest -q

# Runs the 10 README questions through the live system and fills in the README answers.
questions: seed ingest
	$(PY) scripts/run_questions.py

clean:
	docker compose down -v
	rm -rf .venv logs/*.jsonl
