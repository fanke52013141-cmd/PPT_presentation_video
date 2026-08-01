CREATE TABLE IF NOT EXISTS projects (
    id VARCHAR NOT NULL PRIMARY KEY,
    name VARCHAR NOT NULL,
    description VARCHAR,
    current_step INTEGER DEFAULT 1,
    status VARCHAR DEFAULT 'active',
    step_status TEXT DEFAULT '{}',
    created_at DATETIME,
    updated_at DATETIME,
    run_dir VARCHAR NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_projects_id ON projects (id);

CREATE TABLE IF NOT EXISTS settings (
    key VARCHAR NOT NULL PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_settings_key ON settings (key);
