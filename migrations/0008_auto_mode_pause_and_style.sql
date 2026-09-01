-- Auto-mode enhancement: per-project manual pause steps and image style template.
--
-- manual_pause_steps stores a JSON array of module names that should pause
-- for manual interaction during one-click automation.  Default '[]' means
-- fully automatic (no pauses).  Valid values: "digital_human", "mask",
-- "narration".
--
-- image_style_template stores the template id selected at project creation
-- time.  Default 'default' matches the built-in universal template.

ALTER TABLE projects ADD COLUMN manual_pause_steps TEXT NOT NULL DEFAULT '[]';
ALTER TABLE projects ADD COLUMN image_style_template TEXT NOT NULL DEFAULT 'default';
