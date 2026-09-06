-- Production and presentation intent are distinct from legacy AI/MASK flags.
-- Existing projects retain their historical reveal behavior; new projects
-- default to guided creation and complete-frame presentation.
ALTER TABLE projects ADD COLUMN production_mode VARCHAR(32) NOT NULL DEFAULT 'guided';
ALTER TABLE projects ADD COLUMN presentation_mode VARCHAR(32) NOT NULL DEFAULT 'full_frame';

UPDATE projects
SET presentation_mode = CASE
    WHEN mask_enabled = 1 THEN 'reveal'
    ELSE 'full_frame'
END
WHERE presentation_mode IS NULL OR presentation_mode = '';
