ALTER TABLE projects ADD COLUMN creation_config_package_id VARCHAR;
ALTER TABLE projects ADD COLUMN creation_config_version INTEGER;
ALTER TABLE projects ADD COLUMN creation_config_hash VARCHAR;

CREATE INDEX IF NOT EXISTS ix_projects_creation_config_package_id
    ON projects (creation_config_package_id);
