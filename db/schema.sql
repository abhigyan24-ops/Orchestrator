-- =============================================================
-- Multi-Agent Orchestrator — PostgreSQL Schema
-- =============================================================
-- All status columns use CHECK constraints for database-level
-- enforcement. Application-layer validation is a second defense.
-- =============================================================

-- ---------------------------------------------------------
-- tool_skills: which (tool, model) pair is best for which
-- task category, in priority order.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS tool_skills (
    id              SERIAL PRIMARY KEY,
    tool_name       TEXT NOT NULL,
    model_name      TEXT NOT NULL DEFAULT '',
    task_category   TEXT NOT NULL,
    priority        INTEGER NOT NULL,
    notes           TEXT,

    UNIQUE (tool_name, model_name, task_category)
);

CREATE INDEX IF NOT EXISTS idx_tool_skills_category_priority
    ON tool_skills (task_category, priority);

-- ---------------------------------------------------------
-- tasks: the task board.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS tasks (
    id              SERIAL PRIMARY KEY,
    project_id      TEXT NOT NULL,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL,
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN (
                        'pending', 'ready', 'blocked',
                        'in_progress', 'done', 'failed',
                        'waiting_quota'
                    )),
    assigned_tool   TEXT,
    assigned_model  TEXT,
    depends_on      INTEGER REFERENCES tasks(id)
                    ON DELETE SET NULL,
    repo_url        TEXT,
    branch          TEXT,
    target_folder   TEXT,
    base_branch     TEXT DEFAULT 'main',
    pr_url          TEXT,
    result_summary  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_project_status
    ON tasks (project_id, status);

CREATE INDEX IF NOT EXISTS idx_tasks_depends_on
    ON tasks (depends_on);

-- ---------------------------------------------------------
-- api_credentials: the account/key pool.
-- api_key values must be Fernet-encrypted before INSERT.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS api_credentials (
    id              SERIAL PRIMARY KEY,
    tool_name       TEXT NOT NULL,
    account_label   TEXT NOT NULL,
    api_key         TEXT NOT NULL,
    sequence_order  INTEGER NOT NULL,
    status          TEXT NOT NULL DEFAULT 'available'
                    CHECK (status IN (
                        'available', 'exhausted', 'unknown'
                    )),
    tool_type       TEXT NOT NULL
                    CHECK (tool_type IN (
                        'api_based', 'ide_native'
                    )),

    UNIQUE (tool_name, account_label)
);

-- ---------------------------------------------------------
-- quota_status: per-(tool, model) quota tracking.
-- CRITICAL: composite PK on (tool_name, model_name) because
-- tools like Antigravity / Claude expose multiple models
-- with SEPARATE quotas under one app.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS quota_status (
    tool_name       TEXT NOT NULL,
    model_name      TEXT NOT NULL DEFAULT '',
    account_label   TEXT,
    status          TEXT NOT NULL DEFAULT 'available'
                    CHECK (status IN (
                        'available', 'exhausted', 'unknown'
                    )),
    last_checked    TIMESTAMPTZ,
    reset_at        TIMESTAMPTZ,
    notes           TEXT,

    PRIMARY KEY (tool_name, model_name)
);

-- ---------------------------------------------------------
-- quota_log: append-only audit trail of every call attempt.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS quota_log (
    id              SERIAL PRIMARY KEY,
    tool_name       TEXT NOT NULL,
    model_name      TEXT NOT NULL DEFAULT '',
    task_id         INTEGER REFERENCES tasks(id)
                    ON DELETE SET NULL,
    event           TEXT NOT NULL
                    CHECK (event IN (
                        'call_success', 'call_failed',
                        'quota_exceeded'
                    )),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_response    TEXT
);

CREATE INDEX IF NOT EXISTS idx_quota_log_tool_model
    ON quota_log (tool_name, model_name);

-- ---------------------------------------------------------
-- project_context: replaces re-explaining the project
-- each session.
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS project_context (
    project_id      TEXT PRIMARY KEY,
    architecture    TEXT,
    progress_log    TEXT,
    handoff_notes   TEXT,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
