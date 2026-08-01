CREATE TABLE IF NOT EXISTS artifact_records (
    id VARCHAR NOT NULL PRIMARY KEY,
    project_id VARCHAR NOT NULL,
    artifact_type VARCHAR NOT NULL,
    filename VARCHAR NOT NULL,
    relative_path VARCHAR NOT NULL,
    mime_type VARCHAR NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    source_fingerprint TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_artifact_records_id ON artifact_records (id);
CREATE INDEX IF NOT EXISTS ix_artifact_records_project_id ON artifact_records (project_id);
CREATE INDEX IF NOT EXISTS ix_artifact_records_artifact_type ON artifact_records (artifact_type);

CREATE TABLE IF NOT EXISTS local_jobs (
    id VARCHAR NOT NULL PRIMARY KEY,
    project_id VARCHAR NOT NULL,
    job_type VARCHAR NOT NULL,
    status VARCHAR NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    stage VARCHAR NOT NULL DEFAULT 'queued',
    error TEXT,
    result_artifact_id VARCHAR,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at DATETIME NOT NULL,
    started_at DATETIME,
    finished_at DATETIME,
    updated_at DATETIME NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_local_jobs_id ON local_jobs (id);
CREATE INDEX IF NOT EXISTS ix_local_jobs_project_id ON local_jobs (project_id);
CREATE INDEX IF NOT EXISTS ix_local_jobs_job_type ON local_jobs (job_type);
CREATE INDEX IF NOT EXISTS ix_local_jobs_status ON local_jobs (status);
