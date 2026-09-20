"""Shared constants and masked-source pair helpers for AI Mask stages."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import time

MASK_COLORS = (
    "#E84A5F", "#1B998B", "#F6AE2D", "#3D5A80",
    "#7B2CBF", "#2F80ED", "#D45113", "#4C956C",
)
AI_MASK_VISION_TIMEOUT_SEC = 180.0
AI_MASK_MIN_FOREGROUND_COVERAGE = 0.995

# Single source of truth for the reveal pipeline version.  Server, reveal
# builder, validator, and PPTX export must all reference this constant.
# v6 adds the raw source-pair path: layered slides extract reveal pixels from
# the pre-normalization image while static pages keep the normalized master.
REVEAL_PIPELINE_VERSION = "exact_rle_mask_with_manual_corrections_v6"

# Raw source pair: uploads and generated slides are stored normalized
# (outer-connected near-white washed to #FFFFFF) for static/PPTX consumers.
# AI Mask detection and reveal-layer extraction additionally need the
# pre-wash pixels (pale boards, antialiased glyph halos), so a raw sidecar is
# kept next to the master and bound to it by a content-hash marker.  Any
# master mutation without re-sealing invalidates the pair and every consumer
# falls back to the normalized master byte-for-byte.
MASK_SOURCE_PAIR_SCHEMA = "mask_source_pair_v1"
# Near-white pixels below this channel value are never boundary-removed when
# the raw pair is active, so intentional pale content survives in the layer.
RAW_SOURCE_CUTOUT_HARD_MIN_CHANNEL = 254


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def mask_source_raw_path(master_path: Path) -> Path:
    return master_path.with_name(f"{master_path.stem}.raw.png")


def mask_source_marker_path(master_path: Path) -> Path:
    return master_path.with_name(f"{master_path.stem}.raw.sha256")


def seal_mask_source_pair(master_path: Path) -> Path | None:
    """Bind the current master bytes to an existing raw sidecar."""
    raw_path = mask_source_raw_path(master_path)
    marker_path = mask_source_marker_path(master_path)
    if not master_path.exists() or not raw_path.exists():
        try:
            marker_path.unlink()
        except FileNotFoundError:
            pass
        return None
    payload = {
        "schema": MASK_SOURCE_PAIR_SCHEMA,
        "master_sha256": _sha256_file(master_path),
        "raw_sha256": _sha256_file(raw_path),
    }
    tmp_path = marker_path.with_name(f".{marker_path.name}.{os.urandom(8).hex()}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_path, marker_path)
    return marker_path


def resolve_mask_source_master(master_path: Path) -> Path | None:
    """Return the raw sidecar only when its marker matches the current bytes."""
    raw_path = mask_source_raw_path(master_path)
    marker_path = mask_source_marker_path(master_path)
    if not master_path.exists() or not raw_path.exists() or not marker_path.exists():
        return None
    try:
        payload: Any = json.loads(marker_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != MASK_SOURCE_PAIR_SCHEMA:
        return None
    try:
        if _sha256_file(master_path) != payload.get("master_sha256"):
            return None
        if _sha256_file(raw_path) != payload.get("raw_sha256"):
            return None
    except OSError:
        return None
    return raw_path


def remove_mask_source_pair(master_path: Path) -> None:
    for path in (mask_source_raw_path(master_path), mask_source_marker_path(master_path)):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def rename_mask_source_pair(master_path: Path, new_master_path: Path) -> bool:
    """Move a raw pair onto a new master path; the content marker stays valid."""
    raw_path = mask_source_raw_path(master_path)
    marker_path = mask_source_marker_path(master_path)
    if not raw_path.exists():
        remove_mask_source_pair(new_master_path)
        return False
    os.replace(raw_path, mask_source_raw_path(new_master_path))
    if marker_path.exists():
        os.replace(marker_path, mask_source_marker_path(new_master_path))
    else:
        try:
            mask_source_marker_path(new_master_path).unlink()
        except FileNotFoundError:
            pass
    return True


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
