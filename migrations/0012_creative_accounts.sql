CREATE TABLE IF NOT EXISTS accounts (
    id VARCHAR(80) NOT NULL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    description VARCHAR(2000),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    default_creation_config_package_id VARCHAR(120),
    default_creation_config_version INTEGER,
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL
);

INSERT INTO accounts (
    id, name, description, status, created_at, updated_at
)
SELECT 'default', '默认创作账号', '由旧版全局设置迁移而来', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE id = 'default');

ALTER TABLE projects ADD COLUMN account_id VARCHAR(80) NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS ix_projects_account_id ON projects (account_id);

CREATE TABLE IF NOT EXISTS agent_tokens (
    id VARCHAR(80) NOT NULL PRIMARY KEY,
    account_id VARCHAR(80) NOT NULL,
    name VARCHAR(200) NOT NULL,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    scopes VARCHAR(1000) NOT NULL DEFAULT 'project:read,project:write,pipeline:write,artifact:read',
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at DATETIME NOT NULL,
    last_used_at DATETIME
);
CREATE INDEX IF NOT EXISTS ix_agent_tokens_account_id ON agent_tokens (account_id);
