"""W0 metric tests for the AI Mask benchmark: scorer controls, determinism,
and the no-answer-leak guard for the vision payload.

These tests are offline-safe: no server import, no database, no network.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from checks.ai_mask_benchmark import project_fixture as pf
from checks.ai_mask_benchmark.project_fixture import DEFAULT_BUNDLE, FixtureCase

BUNDLE = DEFAULT_BUNDLE
pytestmark = pytest.mark.skipif(
    not (BUNDLE / "scripts" / "evaluate.py").exists(),
    reason=f"handoff bundle missing at {BUNDLE}",
)


def case(case_id: str) -> FixtureCase:
    folder = BUNDLE / "fixtures" / case_id
    assert folder.exists(), folder
    return FixtureCase(case_id, folder)


def group_masks(case_dir: Path) -> dict[str, np.ndarray]:
    truth = json.loads((case_dir / "ground_truth.json").read_text(encoding="utf-8"))
    labels = np.asarray(Image.open(case_dir / "ownership.png"))
    return {
        str(group["id"]): (labels == int(group["label"]))
        for group in truth["groups"]
    }


@pytest.fixture()
def case_01() -> FixtureCase:
    return case("case_01_clean")


def test_ground_truth_scores_perfect(case_01: FixtureCase) -> None:
    masks = group_masks(case_01.folder)
    eval_module = pf.load_eval(BUNDLE)
    score = eval_module.score(case_01.folder, masks)
    assert score["macro_group_recall"] == 1.0
    assert score["correct_ownership_ratio"] == 1.0
    if score["protected_white_recall"] is not None:
        assert score["protected_white_recall"] == 1.0
    assert score["overlap_pixels_all_canvas"] == 0
    assert score["unknown_group_ids"] == [] and score["missing_group_ids"] == []
    assert score["wrong_or_overlapping_truth_pixels"] == 0


def test_empty_swapped_and_overlapping_controls_fail(case_01: FixtureCase) -> None:
    eval_module = pf.load_eval(BUNDLE)
    masks = group_masks(case_01.folder)
    empty = {gid: np.zeros_like(mask, dtype=bool) for gid, mask in masks.items()}
    score = eval_module.score(case_01.folder, empty)
    assert score["macro_group_recall"] == 0.0
    assert score["ink_recall"] == 0.0

    ids = sorted(masks)
    swapped = {ids[i]: masks[ids[(i + 1) % len(ids)]] for i in range(len(ids))}
    score = eval_module.score(case_01.folder, swapped)
    assert score["macro_group_recall"] < 0.2
    assert score["wrong_or_overlapping_truth_pixels"] > 0

    union = np.zeros_like(masks[ids[0]], dtype=bool)
    for mask in masks.values():
        union |= mask
    overlapped = {gid: union.copy() for gid in ids}
    score = eval_module.score(case_01.folder, overlapped)
    assert score["overlap_pixels_all_canvas"] > 0
    assert score["macro_ownership_iou_on_truth"] < 0.5


def test_prediction_export_round_trips_manifest_rle(tmp_path: Path, case_01: FixtureCase) -> None:
    masks = group_masks(case_01.folder)
    height, width = next(iter(masks.values())).shape

    def to_rle(mask: np.ndarray) -> dict:
        runs = []
        for y in range(height):
            xs = np.flatnonzero(mask[y])
            if not len(xs):
                continue
            start = previous = int(xs[0])
            for x in [int(v) for v in xs[1:]] + [-2]:
                if x != previous + 1:
                    runs.append([y, start, previous + 1])
                    start = x
                previous = x
        return {"encoding": "row_runs_v1", "width": width, "height": height, "runs": runs}

    manifest = {
        "version": "reveal_manifest_v3",
        "slides": [
            {
                "slide_id": case_01.case_id,
                "groups": [
                    {
                        "id": gid,
                        "visual_group_id": gid,
                        "manual_mask": {
                            "source": "ai_auto_mask_v3_exact_rle",
                            "strokes": [],
                            "rle": to_rle(mask),
                        },
                    }
                    for gid, mask in masks.items()
                ]
                + [
                    {
                        "id": "__static_title_header__",
                        "is_static_header": True,
                        "manual_mask": {"strokes": [], "rle": to_rle(np.zeros((height, width), bool))},
                    }
                ],
                "ai_mask_status": {"review_issues": []},
            }
        ],
    }
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "reveal_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    prediction = pf.export_prediction(run_dir, case_01.case_id, tmp_path / "prediction.json")
    assert {group["group_id"] for group in prediction["groups"]} == set(masks)
    assert "__static_title_header__" not in {group["group_id"] for group in prediction["groups"]}

    eval_module = pf.load_eval(BUNDLE)
    loaded, payload = eval_module.masks_from_prediction(
        tmp_path / "prediction.json", case_01.case_id, (height, width)
    )
    assert payload["coordinate_space"] == "full_slide"
    for gid, mask in masks.items():
        assert np.array_equal(loaded[gid], mask)

    # A group the annotator left unmasked is exported as an absent prediction so
    # the scorer can report it under ``missing_group_ids``.
    manifest["slides"][0]["groups"].append(
        {"id": "g_unmasked", "visual_group_id": "g_unmasked", "manual_mask": {"strokes": [], "rle": []}}
    )
    (run_dir / "reveal_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    prediction = pf.export_prediction(run_dir, case_01.case_id, tmp_path / "sparse.json")
    assert prediction["unmasked_group_ids"] == ["g_unmasked"]
    assert "g_unmasked" not in {group["group_id"] for group in prediction["groups"]}

    # Manual correction strokes must be rejected, never silently ignored.
    manifest["slides"][0]["groups"][0]["manual_mask"]["strokes"] = [
        {"points": [[0, 0], [4, 4]], "mode": "paint"}
    ]
    (run_dir / "reveal_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="manual strokes"):
        pf.export_prediction(run_dir, case_01.case_id, tmp_path / "bad.json")


def test_detect_elements_is_pixel_deterministic_across_fresh_dirs(tmp_path: Path) -> None:
    from ai_mask_component_detection import detect_elements
    from ai_mask_engine import normalize_settings

    settings = normalize_settings({})
    case_ids = ("case_02_gap_4", "case_05_fragments", "case_09_pale")
    payload_a: dict[str, dict] = {}
    payload_b: dict[str, dict] = {}
    for bucket, root in (("a", tmp_path / "a"), ("b", tmp_path / "b")):
        store = payload_a if bucket == "a" else payload_b
        for case_id in case_ids:
            fixture = case(case_id)
            payload = copy.deepcopy(
                detect_elements(fixture.visual_draft, root / case_id, settings, None)
            )
            # Wall-clock stage timings are expected to differ run to run; only
            # the pixel facts and grouping decisions must be reproducible.
            for key in ("detect_seconds", "elapsed_ms", "stage_timing_ms"):
                payload.pop(key, None)
            assert payload["cache_hit"] is False
            store[case_id] = payload
    for case_id in case_ids:
        digest_a = hashlib.sha256(
            json.dumps(payload_a[case_id], sort_keys=True).encode("utf-8")
        ).hexdigest()
        digest_b = hashlib.sha256(
            json.dumps(payload_b[case_id], sort_keys=True).encode("utf-8")
        ).hexdigest()
        assert digest_a == digest_b, f"{case_id} detection is not deterministic"


def test_detect_elements_reports_stage_timing_and_layout_state(tmp_path: Path) -> None:
    from ai_mask_component_detection import detect_elements
    from ai_mask_engine import normalize_settings

    settings = normalize_settings({})
    fixture = case("case_02_gap_4")
    slide_dir = tmp_path / "slide_001"
    payload = detect_elements(fixture.visual_draft, slide_dir, settings, None)
    timing = payload["stage_timing_ms"]
    assert set(("source_hash", "foreground", "morphology", "components")) <= set(timing)
    assert all(float(value) >= 0.0 for value in timing.values())
    assert payload["cache_hit"] is False
    assert payload["layout_detection"]["status"] == "disabled"

    # A cache hit must be reported as such instead of looking like fresh work.
    again = detect_elements(fixture.visual_draft, slide_dir, settings, None)
    assert again["cache_hit"] is True
    assert again["stage_timing_ms"]["components"] == timing["components"]
    assert again["elements"] == payload["elements"]


def _fixture_contract_slide(fixture: FixtureCase) -> dict:
    return pf.build_contract_slide(fixture)


def test_vision_payload_contains_no_answer_leakage(tmp_path: Path) -> None:
    """The serialized model input must not contain ground-truth tokens or labels."""
    from ai_mask_component_detection import detect_elements
    from ai_mask_engine import normalize_settings
    from ai_mask_semantic_matcher import _semantic_objects

    leak_cases = ("case_01_clean", "case_08_repeated", "case_11_sixteen")
    settings = normalize_settings({})
    for case_id in leak_cases:
        fixture = case(case_id)
        truth = json.loads((fixture.folder / "ground_truth.json").read_text(encoding="utf-8"))
        elements_payload = detect_elements(fixture.visual_draft, tmp_path / case_id, settings, None)
        elements = elements_payload["elements"]
        with Image.open(fixture.visual_draft) as image:
            width, height = image.size
        objects = _semantic_objects(elements, width, height)
        slide = _fixture_contract_slide(fixture)
        # Mirror SemanticVisionMatcher.__call__ payload keys exactly.
        payload = {
            "slide": {
                key: slide.get(key)
                for key in (
                    "slide_id", "main_title", "subtitle", "core_message",
                    "body_content", "visual_groups", "narration_beats",
                )
            },
            "semantic_objects": [
                {
                    "object_id": obj.get("object_id"),
                    "type": obj.get("type"),
                    "element_count": obj.get("element_count"),
                    "bbox": obj.get("bbox", {}),
                    "center": obj.get("center", {}),
                    "cluster_member_count": obj.get("cluster_member_count", 1),
                }
                for obj in objects
            ],
        }
        blob = json.dumps(payload, ensure_ascii=False)
        for group in truth["groups"]:
            assert f'"label": {group["label"]}' not in blob
            assert "ownership" not in blob and "ground_truth" not in blob
            description = str(group.get("description") or "")
            # Group descriptions are answer-side metadata; only the model-facing
            # narration text may share words with them, never the full entry.
            if description:
                assert json.dumps(group, ensure_ascii=False) not in blob
        assert "answer_overlay" not in blob
