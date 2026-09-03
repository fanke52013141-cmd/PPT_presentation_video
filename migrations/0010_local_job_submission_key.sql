-- Stable render-submission identity.  Existing historical jobs intentionally
-- retain NULL submission_key values and remain readable through LocalJob.
ALTER TABLE local_jobs ADD COLUMN submission_key VARCHAR;
ALTER TABLE local_jobs ADD COLUMN submission_attempt INTEGER NOT NULL DEFAULT 0;

-- A retry retains the same submission key but advances its attempt number, so
-- history is preserved while a duplicate active/successful submission is not.
CREATE UNIQUE INDEX IF NOT EXISTS ux_local_jobs_render_submission_attempt
ON local_jobs (project_id, job_type, submission_key, submission_attempt)
WHERE submission_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_local_jobs_render_submission_key
ON local_jobs (project_id, job_type, submission_key, created_at DESC)
WHERE submission_key IS NOT NULL;
