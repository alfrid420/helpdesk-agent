-- Runs once, on first container start (docker-entrypoint-initdb.d).
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE employees (
    employee_id TEXT PRIMARY KEY CHECK (employee_id ~ '^E[0-9]{3}$'),
    name        TEXT NOT NULL,
    email       TEXT NOT NULL UNIQUE,
    title       TEXT NOT NULL,
    department  TEXT NOT NULL,
    manager_id  TEXT REFERENCES employees (employee_id) DEFERRABLE INITIALLY DEFERRED,
    hire_date   DATE NOT NULL,
    phone       TEXT,
    salary      NUMERIC(10, 2),
    address     TEXT
);

CREATE TABLE leave_balances (
    employee_id      TEXT NOT NULL REFERENCES employees (employee_id) ON DELETE CASCADE,
    leave_type       TEXT NOT NULL CHECK (leave_type IN ('annual', 'sick', 'personal')),
    entitlement_days NUMERIC(5, 1) NOT NULL,
    used_days        NUMERIC(5, 1) NOT NULL,
    PRIMARY KEY (employee_id, leave_type)
);

CREATE TABLE leave_history (
    id          SERIAL PRIMARY KEY,
    employee_id TEXT NOT NULL REFERENCES employees (employee_id) ON DELETE CASCADE,
    leave_type  TEXT NOT NULL CHECK (leave_type IN ('annual', 'sick', 'personal')),
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    days        NUMERIC(4, 1) NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('approved', 'pending', 'rejected', 'cancelled'))
);
CREATE INDEX leave_history_employee_idx ON leave_history (employee_id, start_date DESC);

CREATE TABLE doc_chunks (
    id          SERIAL PRIMARY KEY,
    doc         TEXT NOT NULL,
    section     TEXT NOT NULL,
    chunk_index INT  NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(384) NOT NULL   -- BAAI/bge-small-en-v1.5
);
CREATE INDEX doc_chunks_embedding_idx ON doc_chunks USING hnsw (embedding vector_cosine_ops);

-- Least privilege: the MCP server and the retriever connect as this SELECT-only role,
-- so even a bug in application code cannot write to the database. (Dev-only password.)
CREATE ROLE helpdesk_ro LOGIN PASSWORD 'helpdesk_ro';
GRANT SELECT ON employees, leave_balances, leave_history, doc_chunks TO helpdesk_ro;
