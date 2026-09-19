"""Offline benchmark scoring must detect ownership errors and export safely."""
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from repository_paths import REPO_ROOT
from scripts.ai_mask_benchmark import score_case, selftest
from scripts.ai_mask_export_benchmark import export


def test_score_detects_swaps_overlap_and_missing(tmp_path):
    selftest(Path(REPO_ROOT) / "docs/ai-mask-optimization/validation")


def test_missing_predictions_are_failure(tmp_path):
    case = Path(REPO_ROOT) / "docs/ai-mask-optimization/validation/cases/01_separated"
    report = score_case(case, tmp_path)
    assert not report["passed"]
    assert report["coverage"] == 0


def test_export_validates_before_writing_and_is_read_only(tmp_path):
    manifest = tmp_path / "manifest.json"
    mapping = tmp_path / "mapping.json"
    data = {"slides": [{"slide_id": "slide_001", "groups": [{"id": "real_group", "manual_mask": {
        "rle": {"encoding": "row_runs_v1", "width": 1920, "height": 1080, "runs": [[10, 20, 25]]},
        "strokes": []}}]}]}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    original = manifest.read_bytes()
    mapping.write_text(json.dumps({"group_001": "real_group"}), encoding="utf-8")
    output = tmp_path / "predictions"
    export(manifest, "slide_001", mapping, output)
    assert manifest.read_bytes() == original
    assert np.count_nonzero(np.asarray(Image.open(output / "group_001.png"))) == 5
    with pytest.raises(ValueError, match="existing"):
        export(manifest, "slide_001", mapping, output)
    data["slides"][0]["groups"][0]["manual_mask"]["strokes"] = [{"points": [[1, 2]]}]
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="strokes"):
        export(manifest, "slide_001", mapping, tmp_path / "rejected")
    assert not (tmp_path / "rejected").exists()


def test_export_writes_empty_mask_for_unmatched_group(tmp_path):
    manifest = tmp_path / "manifest.json"
    mapping = tmp_path / "mapping.json"
    data = {"slides": [{"slide_id": "slide_001", "groups": [
        {"id": "matched", "manual_mask": {
            "rle": {"encoding": "row_runs_v1", "width": 1920, "height": 1080, "runs": [[10, 20, 25]]},
            "strokes": []}},
        {"id": "unmatched", "manual_mask": {"strokes": []}},
    ]}]}
    manifest.write_text(json.dumps(data), encoding="utf-8")
    mapping.write_text(json.dumps({"group_001": "matched", "group_002": "unmatched"}), encoding="utf-8")
    output = tmp_path / "predictions"
    export(manifest, "slide_001", mapping, output)
    assert np.count_nonzero(np.asarray(Image.open(output / "group_001.png"))) == 5
    assert np.count_nonzero(np.asarray(Image.open(output / "group_002.png"))) == 0
    notes = json.loads((output / "export_notes.json").read_text(encoding="utf-8"))
    assert set(notes) == {"group_002"}


def test_invalid_prediction_dimensions_rejected(tmp_path):
    case = Path(REPO_ROOT) / "docs/ai-mask-optimization/validation/cases/01_separated"
    Image.new("L", (5, 5)).save(tmp_path / "group_001.png")
    with pytest.raises(ValueError, match="1920x1080"):
        score_case(case, tmp_path)
