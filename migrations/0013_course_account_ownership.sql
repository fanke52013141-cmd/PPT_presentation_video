-- Course trees predate creative accounts.  Legacy courses belong to the
-- default account, matching the legacy project migration in 0012.
ALTER TABLE courses ADD COLUMN account_id VARCHAR(80) NOT NULL DEFAULT 'default';
CREATE INDEX IF NOT EXISTS ix_courses_account_id ON courses (account_id);
CREATE INDEX IF NOT EXISTS ix_courses_account_sort_order ON courses (account_id, sort_order);
