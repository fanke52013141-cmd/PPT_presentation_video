-- Agent API review policy persistence.
--
-- Stores the project-level review policy so that pipeline runs can derive
-- default stop_at checkpoints without requiring the caller to pass stop_at
-- on every request. Values: 'none', 'images_and_video', 'all_stages'.

ALTER TABLE projects ADD COLUMN review_policy TEXT NOT NULL DEFAULT 'none';
