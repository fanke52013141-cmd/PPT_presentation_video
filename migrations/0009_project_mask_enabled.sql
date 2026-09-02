-- Project-level Mask toggle.
--
-- mask_enabled controls whether the one-click pipeline runs the AI Mask
-- annotation and Reveal asset build stages.  1 (default) means the pipeline
-- performs element-level mask annotation and builds reveal layers; 0 means
-- those stages are skipped and every slide renders as a static full-page
-- image (no reveal animation).

ALTER TABLE projects ADD COLUMN mask_enabled INTEGER NOT NULL DEFAULT 1;
