-- Optional per-project Step 2 narration target. NULL preserves the existing
-- unconstrained planning behaviour for every existing project.
ALTER TABLE projects ADD COLUMN target_duration_sec INTEGER NULL;
