"""Shared constants for AI Mask detection, assignment, and manifest output."""

import time

MASK_COLORS = (
    "#E84A5F", "#1B998B", "#F6AE2D", "#3D5A80",
    "#7B2CBF", "#2F80ED", "#D45113", "#4C956C",
)
AI_MASK_VISION_TIMEOUT_SEC = 180.0
AI_MASK_MIN_FOREGROUND_COVERAGE = 0.995

# Single source of truth for the reveal pipeline version.  Server, reveal
# builder, validator, and PPTX export must all reference this constant.
REVEAL_PIPELINE_VERSION = "exact_rle_mask_with_manual_corrections_v5"

# Ownership provenance for every component inside a narration group.  Coverage
# only proves that a pixel has an owner; it never proves the owner is correct,
# so each stage records how ownership was decided:
#   model       - the multimodal matcher claimed this component for this group
#   rule        - a deterministic contract rule (prior box, title band, anchor
#                 seeding, geometry re-check) decided it
#   completion  - the coverage closer attached a leftover component to the
#                 nearest anchor so no foreground pixel stays ownerless
#   manual      - a saved human correction owns the pixels
# Only ``model`` may support a semantic claim; the others stay visible as risk.
ASSIGNMENT_SOURCE_MODEL = "model"
ASSIGNMENT_SOURCE_RULE = "rule"
ASSIGNMENT_SOURCE_COMPLETION = "completion"
ASSIGNMENT_SOURCE_MANUAL = "manual"
ASSIGNMENT_SOURCES: tuple[str, ...] = (
    ASSIGNMENT_SOURCE_MODEL,
    ASSIGNMENT_SOURCE_RULE,
    ASSIGNMENT_SOURCE_COMPLETION,
    ASSIGNMENT_SOURCE_MANUAL,
)

# DocLayout layout-detection outcomes.  Every annotated slide records exactly one
# of them so a degraded page stays diagnosable instead of silently looking like a
# slide that simply has no layout regions.
LAYOUT_STATUS_DISABLED = "disabled"
LAYOUT_STATUS_MISSING_DEPENDENCY = "missing_dependency"
LAYOUT_STATUS_MISSING_MODEL = "missing_model"
LAYOUT_STATUS_SESSION_INIT_FAILED = "session_init_failed"
LAYOUT_STATUS_INFERENCE_FAILED = "inference_failed"
LAYOUT_STATUS_NO_BOXES = "no_boxes"
LAYOUT_STATUS_OK = "ok"
LAYOUT_STATUSES: tuple[str, ...] = (
    LAYOUT_STATUS_DISABLED,
    LAYOUT_STATUS_MISSING_DEPENDENCY,
    LAYOUT_STATUS_MISSING_MODEL,
    LAYOUT_STATUS_SESSION_INIT_FAILED,
    LAYOUT_STATUS_INFERENCE_FAILED,
    LAYOUT_STATUS_NO_BOXES,
    LAYOUT_STATUS_OK,
)

# Canonical stage names for per-slide elapsed reporting.  ``reveal`` is measured
# on the Mask build paths because annotation never builds reveal assets.
AI_MASK_ANNOTATION_STAGES: tuple[str, ...] = (
    "layout_load",
    "layout_infer",
    "foreground",
    "morphology",
    "components",
    "object_prepare",
    "vision",
    "assignment",
    "apply",
)
AI_MASK_STAGE_REVEAL = "reveal"


def elapsed_ms(started: float) -> float:
    """Milliseconds since a ``time.perf_counter()`` mark, rounded for logging."""
    return round((time.perf_counter() - started) * 1000.0, 1)
