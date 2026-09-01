-- Agent API idempotency persistence + optimistic locking.
--
-- Adds a monotonically increasing revision to projects for Agent-side
-- optimistic locking (Web UI paths do not bump revision). The idempotency
-- table stores request fingerprints and cached responses so that retried
-- Agent calls are safely replayed instead of re-executing side effects.

ALTER TABLE projects ADD COLUMN revision INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS agent_idempotency_records (
    scope VARCHAR NOT NULL,
    project_id VARCHAR NOT NULL DEFAULT '',
    idempotency_key VARCHAR NOT NULL,
    request_fingerprint VARCHAR(64) NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'in_progress',
    response_json TEXT,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    PRIMARY KEY (scope, project_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS ix_agent_idempotency_records_project
    ON agent_idempotency_records (project_id, created_at);
