"""Stage A raw/normalized dual-image pipeline: pair, wash, and layer tests."""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai_mask_contracts import (  # noqa: E402
    RAW_SOURCE_CUTOUT_HARD_MIN_CHANNEL,
    REVEAL_PIPELINE_VERSION,
    mask_source_marker_path,
    mask_source_raw_path,
    remove_mask_source_pair,
    rename_mask_source_pair,
    resolve_mask_source_master,
    seal_mask_source_pair,
)
from ai_provider_service import process_and_save_image  # noqa: E402
from scripts.build_reveal_scene import compose_slide  # noqa: E402


def make_canvas(path: Path, pale_bar: tuple[int, int, int, int] | None) -> Image.Image:
    image = Image.new("RGB", (320, 180), "#ffffff")
    if pale_bar is not None:
        draw = ImageDraw.Draw(image)
        draw.rectangle(pale_bar, fill=(248, 248, 248))
    image.save(path)
    return image


def painted_group(group_id: str, points: list[tuple[int, int]], width: int) -> dict:
    return {
        "id": group_id,
        "role": "content_body",
        "manual_mask": {
            "strokes": [{
                "mode": "paint",
                "size": width,
                "points": [{"x": x, "y": y} for x, y in points],
            }]
        },
        "reveal": {"type": "crop_fade_up"},
    }


# 1. seal/resolve round trip and every breakage fallback.
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    master = root / "visual_draft.png"
    make_canvas(master, None)
    assert resolve_mask_source_master(master) is None
    raw = mask_source_raw_path(master)
    make_canvas(raw, (80, 85, 160, 95))
    # Unsealed pair must never be trusted.
    assert resolve_mask_source_master(master) is None
    assert seal_mask_source_pair(master) == mask_source_marker_path(master)
    assert resolve_mask_source_master(master) == raw
    # Master bytes changed out-of-band -> stale pair is rejected.
    make_canvas(master, (0, 0, 1, 1))
    assert resolve_mask_source_master(master) is None
    make_canvas(master, None)
    assert resolve_mask_source_master(master) == raw
    # Raw bytes changed -> rejected.
    make_canvas(raw, (0, 0, 4, 4))
    assert resolve_mask_source_master(master) is None
    make_canvas(raw, (80, 85, 160, 95))
    assert seal_mask_source_pair(master) is not None
    assert resolve_mask_source_master(master) == raw
    # Garbage marker -> rejected.
    mask_source_marker_path(master).write_text("not-json", encoding="utf-8")
    assert resolve_mask_source_master(master) is None
    # Sealing without the raw file drops the marker.
    raw.unlink()
    assert seal_mask_source_pair(master) is None
    assert not mask_source_marker_path(master).exists()
    # remove clears both files.
    make_canvas(raw, None)
    seal_mask_source_pair(master)
    remove_mask_source_pair(master)
    assert not raw.exists() and not mask_source_marker_path(master).exists()

# 2. Candidate rename keeps a content-keyed pair valid; missing candidate
# pair clears the replaced master's stale pair.
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    candidate = root / "visual_candidate.png"
    draft = root / "visual_draft.png"
    make_canvas(candidate, None)
    make_canvas(mask_source_raw_path(candidate), (80, 85, 160, 95))
    seal_mask_source_pair(candidate)
    make_canvas(draft, None)
    make_canvas(mask_source_raw_path(draft), (0, 0, 2, 2))
    seal_mask_source_pair(draft)
    import os as _os

    _os.replace(candidate, draft)
    assert rename_mask_source_pair(
        root / "visual_candidate.png", draft
    ) is True
    resolved = resolve_mask_source_master(draft)
    assert resolved == mask_source_raw_path(draft)
    assert not mask_source_raw_path(root / "visual_candidate.png").exists()
    # Now a draft replacement without its own pair must clear the old pair.
    orphan = root / "visual_candidate.png"
    make_canvas(orphan, None)
    _os.replace(orphan, draft)
    assert rename_mask_source_pair(root / "visual_candidate.png", draft) is False
    assert resolve_mask_source_master(draft) is None
    assert not mask_source_raw_path(draft).exists()

# 3. process_and_save_image keeps pre-wash pale pixels only in the raw file.
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    source = Image.new("RGB", (320, 180), "#ffffff")
    ImageDraw.Draw(source).rectangle((80, 85, 160, 95), fill=(248, 248, 248))
    import io as _io

    buffer = _io.BytesIO()
    source.save(buffer, format="PNG")
    master = root / "visual_draft.png"
    raw = root / "visual_draft.raw.png"
    process_and_save_image(
        buffer.getvalue(),
        str(master),
        target_width=320,
        target_height=180,
        raw_save_path=str(raw),
    )
    master_px = np.asarray(Image.open(master).convert("RGB"))
    raw_px = np.asarray(Image.open(raw).convert("RGB"))
    assert tuple(master_px[90, 120]) == (255, 255, 255)
    assert tuple(raw_px[90, 120]) == (248, 248, 248)

# 4. Reveal layers: no pair keeps legacy behavior (washed slide is white ->
# full-slide fallback); a sealed pair reconstructs the pale board solidly.
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    canvas = {
        "width": 320,
        "height": 180,
        "background": "#fefdf9",
        "subtitle_safe_y": 180,
    }
    groups = [painted_group("board", [(80, 90), (160, 90)], 14)]

    legacy_dir = root / "slides" / "slide_001"
    legacy_dir.mkdir(parents=True)
    legacy_master = legacy_dir / "visual_draft.png"
    make_canvas(legacy_master, None)  # what the upload wash leaves behind
    compose_slide(
        {
            "slide_id": "slide_001",
            "slide_dir": str(legacy_dir),
            "master": str(legacy_master),
            "canvas": canvas,
            "groups": groups,
        },
        root,
        root,
        canvas,
    )
    legacy_report = json.loads((legacy_dir / "reveal_report.json").read_text(encoding="utf-8"))
    assert legacy_report["fallback_full_slide"] is True
    assert "cutout" not in legacy_report  # static fallback keeps the legacy report shape

    pair_dir = root / "slides" / "slide_002"
    pair_dir.mkdir(parents=True)
    pair_master = pair_dir / "visual_draft.png"
    make_canvas(pair_master, None)
    make_canvas(mask_source_raw_path(pair_master), (80, 85, 160, 95))
    seal_mask_source_pair(pair_master)
    compose_slide(
        {
            "slide_id": "slide_002",
            "slide_dir": str(pair_dir),
            "master": str(pair_master),
            "canvas": canvas,
            "groups": groups,
        },
        root,
        root,
        canvas,
    )
    pair_report = json.loads((pair_dir / "reveal_report.json").read_text(encoding="utf-8"))
    pair_scene = json.loads((pair_dir / "scene.json").read_text(encoding="utf-8"))
    assert pair_report["pipeline_version"] == REVEAL_PIPELINE_VERSION == "exact_rle_mask_with_manual_corrections_v6"
    assert pair_report["fallback_full_slide"] is False
    assert pair_report["group_count"] == 1
    assert pair_report["cutout"]["source"] == "raw_pair"
    assert pair_report["cutout"]["hard_min_channel"] == RAW_SOURCE_CUTOUT_HARD_MIN_CHANNEL
    assert pair_report["cutout"]["pale_preservation"] is True
    assert len(pair_report["raw_source_sha256"]) == 64
    assert pair_scene["composition"]["cutout_source"] == "raw_pair"
    crop_path = pair_dir / "assets" / "crops" / "board.png"
    crop = np.asarray(Image.open(crop_path).convert("RGBA"))
    center = crop[90, 120]
    assert center[3] == 255, "pale board center must be fully revealed"
    assert tuple(center[:3]) == (248, 248, 248), "source color must survive"
    group_entry = pair_report["groups"][0]
    assert group_entry["cutout"]["pale_preserved_pixel_count"] > 0

# 5. Wiring guards: the mask pipeline must keep resolving the raw pair and
# the writer must seal after every master mutation.
engine = (ROOT / "ai_mask_engine.py").read_text(encoding="utf-8")
assert "resolve_mask_source_master(master_image_path)" in engine
workflow = (ROOT / "image_workflow_service.py").read_text(encoding="utf-8")
assert workflow.count("seal_mask_source_pair(Path(save_path))") == 2
assert workflow.count('raw_save_path=str(mask_source_raw_path(Path(save_path)))') == 2
assert "mask_source_raw_path(Path(image_path))" in workflow  # safe-zone sync
pptx = (ROOT / "pptx_reveal_export.py").read_text(encoding="utf-8")
assert "resolve_mask_source_master(master_path)" in pptx
builder = (ROOT / "scripts" / "build_reveal_scene.py").read_text(encoding="utf-8")
assert "resolve_mask_source_master(master_path)" in builder
assert "restore_pale_source_content" in builder

print("mask source pair checks passed")
