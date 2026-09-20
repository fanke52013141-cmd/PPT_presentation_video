"""Focused checks for automatic AI Mask detection and mapping."""

import json
import tempfile
from pathlib import Path
import sys
import os
import inspect

from PIL import Image, ImageDraw
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_mask_engine as mask
import ai_mask_semantic_matcher as semantic_matcher
from scripts.build_reveal_scene import manual_mask_alpha
os.environ.setdefault("PPT_STUDIO_DISABLE_ONE_CLICK_ORCHESTRATOR", "1")
import one_click_orchestrator as one_click


class _FakeVisionSettings:
    values = {
        "llm_provider": "volcengine",
        "vision_model": "gpt-4o",
        "llm_model": "doubao-seed-2-1-turbo-260628",
    }

    @classmethod
    def get_setting(cls, key):
        return cls.values.get(key, "")


def _mask_element(element_id: str, x: int, y: int, w: int, h: int) -> dict:
    return {
        "element_id": element_id,
        "bbox": {"x": x, "y": y, "w": w, "h": h},
        "raw_bbox": {"x": x, "y": y, "w": w, "h": h},
        "center": {"x": x + w / 2, "y": y + h / 2},
        "area": w * h,
        "mask_rle": {
            "encoding": "row_runs_v1",
            "width": 320,
            "height": 180,
            "runs": [[row, x, x + w] for row in range(y, y + h)],
        },
    }


def _title_region_fixture() -> tuple[dict, dict]:
    elements = {
        "canvas": {"width": 320, "height": 180},
        "elements": [
            _mask_element("title_a", 20, 10, 40, 12),
            _mask_element("title_b", 75, 10, 45, 12),
            _mask_element("subtitle_a", 20, 30, 55, 8),
            _mask_element("subtitle_b", 85, 30, 50, 8),
            _mask_element("body", 40, 90, 220, 40),
        ],
        "residual_elements": [],
    }
    regions = {
        "main_title": {"x": 0, "y": 0, "w": 320, "h": 27},
        "subtitle": {"x": 0, "y": 27, "w": 320, "h": 25},
        "combined": {"x": 0, "y": 0, "w": 320, "h": 52},
    }
    return elements, regions


def test_title_and_subtitle_fragments_follow_narrated_title_group():
    elements, regions = _title_region_fixture()
    slide = {
        "slide_id": "slide_001",
        "main_title": "主标题",
        "subtitle": "副标题",
        "visual_groups": [
            {"id": "opening", "role": "title"},
            {"id": "body_group", "role": "body"},
        ],
        "narration_beats": [
            {"id": "beat_opening", "group_id": "opening", "spoken_text": "先看标题和副标题。"},
            {"id": "beat_body", "group_id": "body_group", "spoken_text": "再讲正文。"},
        ],
    }
    payload = {
        "matches": [
            {"group_id": "opening", "narration_beat_id": "beat_opening", "element_ids": ["title_a"], "confidence": 0.9},
            {"group_id": "body_group", "narration_beat_id": "beat_body", "element_ids": ["title_b", "subtitle_a", "subtitle_b", "body"], "confidence": 0.9},
        ],
        "unmatched_groups": [],
        "warnings": [],
    }
    consolidated = mask._consolidate_title_regions(payload, elements, slide, regions)
    assert consolidated["title_region_policy"] == "narrated_title_and_subtitle_masks"
    assert consolidated["static_element_ids"] == []
    assert consolidated["static_group_ids"] == []
    assert set(consolidated["forced_element_owners"]) == {"title_a", "title_b", "subtitle_a", "subtitle_b"}
    completed = mask._complete_component_coverage(consolidated, elements, slide)
    matches = {item["group_id"]: set(item["element_ids"]) for item in completed["matches"]}
    assert matches["opening"] == {"title_a", "title_b", "subtitle_a", "subtitle_b"}
    assert matches["body_group"] == {"body"}
    assert completed["quality"]["static_header_pixel_count"] == 0
    assert completed["quality"]["passed"] is True
    manifest_slide = {"slide_id": "slide_001", "groups": [], "semantic_blocks": []}
    applied = mask._apply(
        {"slides": [manifest_slide]},
        slide,
        elements,
        completed,
        mask.normalize_settings({"overwrite_existing_ai_mask": True}),
    )
    assert applied["updated"] == 2
    assert not any(group.get("id") == "__static_title_header__" for group in manifest_slide["groups"])
    opening = next(group for group in manifest_slide["groups"] if group.get("visual_group_id") == "opening")
    assert opening["manual_mask"]["rle"]["runs"]
    assert opening.get("is_static") is not True


def test_title_and_subtitle_use_distinct_narrated_groups_when_available():
    elements, regions = _title_region_fixture()
    slide = {
        "slide_id": "slide_001",
        "main_title": "主标题",
        "subtitle": "副标题",
        "visual_groups": [
            {"id": "title_group", "role": "title"},
            {"id": "subtitle_group", "role": "subtitle"},
            {"id": "body_group", "role": "body"},
        ],
        "narration_beats": [
            {"id": "beat_title", "group_id": "title_group", "spoken_text": "这是核心结论。"},
            {"id": "beat_subtitle", "group_id": "subtitle_group", "spoken_text": "这是结论的解释。"},
            {"id": "beat_body", "group_id": "body_group", "spoken_text": "这是正文。"},
        ],
    }
    payload = {
        "matches": [
            {"group_id": "title_group", "narration_beat_id": "beat_title", "element_ids": ["title_a"], "confidence": 0.9},
            {"group_id": "subtitle_group", "narration_beat_id": "beat_subtitle", "element_ids": ["subtitle_a"], "confidence": 0.9},
            {"group_id": "body_group", "narration_beat_id": "beat_body", "element_ids": ["body"], "confidence": 0.9},
        ],
        "unmatched_groups": [],
        "warnings": [],
    }
    consolidated = mask._consolidate_title_regions(payload, elements, slide, regions)
    assert consolidated["title_region_policy"] == "narrated_title_and_subtitle_masks"
    assert consolidated["static_group_ids"] == []
    assert consolidated["static_element_ids"] == []
    matches = {item["group_id"]: set(item["element_ids"]) for item in consolidated["matches"]}
    assert matches["title_group"] == {"title_a", "title_b"}
    assert matches["subtitle_group"] == {"subtitle_a", "subtitle_b"}
    assert matches["body_group"] == {"body"}


def test_title_without_any_narration_remains_static_context():
    elements, regions = _title_region_fixture()
    slide = {
        "slide_id": "slide_001",
        "main_title": "主标题",
        "subtitle": "副标题",
        "visual_groups": [{"id": "title_group", "role": "title"}],
        "narration_beats": [],
    }
    consolidated = mask._consolidate_title_regions(
        {"matches": [], "unmatched_groups": ["title_group"]},
        elements,
        slide,
        regions,
    )
    assert consolidated["title_region_policy"] == "static_header_without_narration"
    assert set(consolidated["static_element_ids"]) == {"title_a", "title_b", "subtitle_a", "subtitle_b"}
    assert consolidated["static_group_ids"] == ["title_group"]


def test_legacy_title_without_title_beat_never_falls_back_to_body_group():
    elements, regions = _title_region_fixture()
    slide = {
        "slide_id": "slide_001",
        "main_title": "主标题",
        "subtitle": "副标题",
        "visual_groups": [
            {"id": "title_group", "role": "title"},
            {"id": "body_group", "role": "body"},
        ],
        "narration_beats": [
            {"id": "beat_body", "group_id": "body_group", "spoken_text": "只讲正文。"},
        ],
    }
    payload = {
        "matches": [
            {
                "group_id": "body_group",
                "narration_beat_id": "beat_body",
                "element_ids": ["title_a", "title_b", "subtitle_a", "subtitle_b", "body"],
                "confidence": 0.9,
            }
        ],
        "unmatched_groups": ["title_group"],
        "warnings": [],
    }
    consolidated = mask._consolidate_title_regions(payload, elements, slide, regions)
    assert consolidated["title_region_policy"] == "static_header_without_narration"
    assert consolidated["static_group_ids"] == ["title_group"]
    assert set(consolidated["static_element_ids"]) == {
        "title_a", "title_b", "subtitle_a", "subtitle_b",
    }
    assert consolidated["forced_element_owners"] == {}
    body_match = next(item for item in consolidated["matches"] if item["group_id"] == "body_group")
    assert body_match["element_ids"] == ["body"]

    completed = mask._complete_component_coverage(consolidated, elements, slide)
    completed_body = next(item for item in completed["matches"] if item["group_id"] == "body_group")
    assert completed_body["element_ids"] == ["body"]
    assert completed["quality"]["static_header_pixel_count"] > 0
    assert completed["quality"]["passed"] is True


def test_every_narrated_group_gets_an_independent_visual_anchor():
    elements, regions = _title_region_fixture()
    elements["elements"].append(_mask_element("summary", 250, 140, 50, 20))
    slide = {
        "slide_id": "slide_001",
        "main_title": "主标题",
        "subtitle": "副标题",
        "visual_groups": [
            {"id": "opening", "role": "title"},
            {"id": "image_group", "role": "body"},
            {"id": "summary_group", "role": "body"},
        ],
        "narration_beats": [
            {"id": "beat_opening", "group_id": "opening", "spoken_text": "开场。"},
            {"id": "beat_image", "group_id": "image_group", "spoken_text": "讲图片。"},
            {"id": "beat_summary", "group_id": "summary_group", "spoken_text": "讲总结。"},
        ],
    }
    swallowed = {
        "matches": [{
            "group_id": "opening",
            "narration_beat_id": "beat_opening",
            "element_ids": ["title_a", "title_b", "subtitle_a", "subtitle_b", "body", "summary"],
            "confidence": 0.9,
        }],
        "unmatched_groups": ["image_group", "summary_group"],
        "warnings": [],
    }
    consolidated = mask._consolidate_title_regions(swallowed, elements, slide, regions)
    anchored = mask._ensure_narrated_group_anchors(consolidated, elements, slide)
    assert anchored["unmatched_groups"] == []
    assert anchored["anchor_policy"] == "one_visual_island_per_narrated_group"
    owners = anchored["forced_element_owners"]
    assert {"image_group", "summary_group"}.issubset(set(owners.values()))
    assert all(owners[element_id] == "opening" for element_id in {"title_a", "title_b", "subtitle_a", "subtitle_b"})
    assert anchored["static_element_ids"] == []
    by_group = {item["group_id"]: set(item["element_ids"]) for item in anchored["matches"]}
    assert by_group["opening"] == {"title_a", "title_b", "subtitle_a", "subtitle_b"}


def test_existing_anchor_is_not_stolen_when_seeding_missing_group():
    elements = {
        "canvas": {"width": 320, "height": 180},
        "elements": [
            _mask_element("existing_anchor", 20, 50, 180, 80),
            _mask_element("available_anchor", 230, 70, 60, 40),
        ],
        "residual_elements": [],
    }
    slide = {
        "narration_beats": [
            {"id": "beat_a", "group_id": "group_a"},
            {"id": "beat_b", "group_id": "group_b"},
        ],
    }
    payload = {
        "matches": [{
            "group_id": "group_a",
            "narration_beat_id": "beat_a",
            "element_ids": ["existing_anchor"],
            "confidence": 0.9,
        }],
        "unmatched_groups": ["group_b"],
    }
    anchored = mask._ensure_narrated_group_anchors(payload, elements, slide)
    by_group = {item["group_id"]: item["element_ids"] for item in anchored["matches"]}
    assert by_group["group_a"] == ["existing_anchor"]
    assert by_group["group_b"] == ["available_anchor"]
    assert anchored["unmatched_groups"] == []


def test_nearby_icon_is_absorbed_by_closest_large_visual_island():
    elements = {
        "canvas": {"width": 320, "height": 180},
        "elements": [
            _mask_element("left_island", 20, 45, 100, 90),
            _mask_element("right_island", 210, 45, 90, 90),
            _mask_element("near_left_check", 126, 62, 14, 14),
        ],
        "residual_elements": [],
    }
    # The vision model made the same kind of semantic mistake observed on
    # slide 3: the check icon was put in the right group despite being next to
    # the left illustration. Geometry must correct that ownership.
    payload = {
        "matches": [
            {"group_id": "left", "element_ids": ["left_island"], "confidence": 0.9},
            {"group_id": "right", "element_ids": ["right_island", "near_left_check"], "confidence": 0.9},
        ],
        "unmatched_groups": [],
    }
    completed = mask._complete_component_coverage(payload, elements)
    by_group = {item["group_id"]: set(item["element_ids"]) for item in completed["matches"]}
    assert "near_left_check" in by_group["left"]
    assert "near_left_check" not in by_group["right"]
    assert completed["component_assignment_policy"] == "dominant_island_2d_absorption_v2"


def test_atomicity_conflict_blocks_semantic_quality_and_preserves_model_warning():
    elements = {
        "canvas": {"width": 320, "height": 180},
        "elements": [
            _mask_element("left_card", 20, 60, 80, 60),
            _mask_element("right_card", 220, 60, 80, 60),
        ],
        "residual_elements": [],
    }
    slide = {
        "slide_id": "slide_001",
        "visual_groups": [
            {
                "id": "body_group",
                "role": "content_body",
                "visual_anchor": "左侧视觉岛展示问题，右侧视觉岛展示方案。",
            }
        ],
        "narration_beats": [{"id": "beat_001", "group_id": "body_group"}],
    }
    completed = mask._complete_component_coverage(
        {
            "matches": [
                {
                    "group_id": "body_group",
                    "element_ids": ["left_card", "right_card"],
                    "confidence": 0.95,
                }
            ],
            "warnings": [
                {
                    "type": "insufficient_visual_groups_for_independent_objects",
                    "object_ids": ["obj_left", "obj_right"],
                }
            ],
        },
        elements,
        slide,
    )
    assert completed["quality"]["passed"] is False
    assert any(
        issue.get("type") == "group_contains_multiple_independent_visual_islands"
        for issue in completed["semantic_quality"]["blocking_errors"]
    )
    assert any(
        issue.get("type") == "insufficient_visual_groups_for_independent_objects"
        for issue in completed["semantic_quality"]["blocking_errors"]
    )
    assert any(
        warning.get("type") == "insufficient_visual_groups_for_independent_objects"
        for warning in completed["warnings"]
        if isinstance(warning, dict)
    )


def test_volcengine_ai_mask_uses_provider_model_and_single_timeout_policy():
    resolved, configured = mask._resolved_vision_model(_FakeVisionSettings)
    assert resolved == "doubao-seed-2-1-turbo-260628"
    assert configured == "gpt-4o"
    source = inspect.getsource(semantic_matcher.SemanticVisionMatcher.__call__)
    assert "step2_llm_vendor_options" in source
    assert "AI_MASK_VISION_TIMEOUT_SEC" in source
    assert "_is_timeout(capabilities, exc)" in source


def test_semantic_object_match_expands_element_ids_without_model_guessing():
    expanded = semantic_matcher._expand_matches(
        {
            "matches": [
                {
                    "group_id": "body_group",
                    "object_ids": ["obj_001"],
                    "element_ids": [],
                    "confidence": 0.95,
                }
            ]
        },
        [{"object_id": "obj_001", "element_ids": ["el_001", "el_002"]}],
        [{"element_id": "el_001"}, {"element_id": "el_002"}],
    )

    assert expanded["matches"][0]["object_ids"] == ["obj_001"]
    assert expanded["matches"][0]["element_ids"] == ["el_001", "el_002"]


def fixture_slide() -> dict:
    return {
        "slide_id": "slide_001",
        "visual_groups": [
            {"id": "group_left", "role": "content_body"},
            {"id": "group_right", "role": "content_body"},
            {"id": "decoration", "role": "decoration"},
        ],
        "narration_beats": [
            {"id": "beat_left", "group_id": "group_left"},
            {"id": "beat_right", "group_id": "group_right"},
        ],
    }


def _two_card_image(slide_dir: Path) -> Path:
    """Two solid cards 3 pixels apart: closing bridges them, ink does not."""
    slide_dir.mkdir(parents=True, exist_ok=True)
    image_path = slide_dir / "visual_draft.png"
    image = Image.new("RGB", (320, 180), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 30, 110, 120), fill="black")
    draw.rectangle((114, 30, 200, 120), fill="#2357A5")
    image.save(image_path)
    return image_path


def _layout_box(x: int, y: int, w: int, h: int, role: str = "figure", confidence: float = 0.9) -> dict:
    return {"box": {"x": x, "y": y, "w": w, "h": h}, "role": role, "confidence": confidence, "class_id": 3}


def test_closing_bridge_pixels_never_enter_a_saved_mask() -> None:
    detection_settings = mask.normalize_settings({
        "min_element_area": 10,
        "component_padding_px": 0,
    })
    with tempfile.TemporaryDirectory() as temp_dir:
        slide_dir = Path(temp_dir) / "slide_001"
        image_path = _two_card_image(slide_dir)
        detected = mask.detect_elements(image_path, slide_dir, detection_settings)

        assert detected["version"] == "auto_elements_v4_ink_separated"
        assert detected["pixel_evidence_separation"] is True
        assert detected["elements"], "the bridged pair must still be detected"
        assert len(detected["elements"]) == 1
        element = detected["elements"][0]
        ink = 91 * 91 + 87 * 91
        # Closing joins the cards (grouping hypothesis), the Mask keeps the ink.
        assert element["source_ink_pixel_count"] == ink
        assert element["area"] == ink
        assert element["mask_pixel_count"] == ink
        assert element["grouping_pixel_count"] == ink + 273
        assert element["bridge_pixel_count"] == 273
        assert detected["source_foreground_pixel_count"] == ink
        assert detected["grouping_pixel_count"] > ink
        gap_columns = range(111, 114)
        for run in element["mask_rle"]["runs"]:
            assert not (run[1] <= min(gap_columns) and run[2] >= max(gap_columns) + 1), run
        assert element.get("atomic_component_ids") is None, (
            "atoms are only recovered when layout boxes can own them"
        )


def test_rollback_switch_restores_the_closing_as_ink_behaviour() -> None:
    detection_settings = mask.normalize_settings({
        "min_element_area": 10,
        "component_padding_px": 0,
        "pixel_evidence_separation": False,
    })
    with tempfile.TemporaryDirectory() as temp_dir:
        slide_dir = Path(temp_dir) / "slide_001"
        image_path = _two_card_image(slide_dir)
        detected = mask.detect_elements(image_path, slide_dir, detection_settings)
        assert detected["pixel_evidence_separation"] is False
        element = detected["elements"][0]
        assert element["bridge_pixel_count"] == 0
        assert element["mask_pixel_count"] > 91 * 91 + 87 * 91


def test_layout_boxes_split_a_bridged_pair_without_reading_box_order() -> None:
    detection_settings = mask.normalize_settings({
        "min_element_area": 10,
        "component_padding_px": 0,
    })
    cards = [
        _layout_box(15, 25, 100, 100),
        _layout_box(110, 25, 95, 100),
    ]
    with tempfile.TemporaryDirectory() as temp_dir:
        slide_dir = Path(temp_dir) / "slide_001"
        image_path = _two_card_image(slide_dir)
        baseline = mask.detect_elements(
            image_path, slide_dir, detection_settings, layout_boxes=cards
        )
        assert [element["element_id"] for element in baseline["elements"]] == [
            "el_auto_001", "el_auto_002",
        ]
        assert [element["bbox"]["x"] for element in baseline["elements"]] == [20, 114]
        assert [element["mask_pixel_count"] for element in baseline["elements"]] == [8281, 7917]
        assert [element["atomic_component_ids"] for element in baseline["elements"]] == [
            ["el_atom_0001"], ["el_atom_0002"],
        ]
        assert baseline["layout_binding"]["merged_element_count"] == 2
        assert baseline["layout_binding"]["unbound_element_ids"] == []

        fingerprint = lambda report: [  # noqa: E731
            (element["bbox"]["x"], element["bbox"]["y"], element["mask_rle"]["runs"])
            for element in report["elements"]
        ]
        for boxes in ([cards[1], cards[0]], cards + [_layout_box(0, 0, 320, 180, "page", 0.99)]):
            shuffled = list(boxes)
            shuffled.reverse()
            outcome = mask.detect_elements(
                image_path, slide_dir, detection_settings, layout_boxes=shuffled
            )
            assert fingerprint(outcome) == fingerprint(baseline), shuffled


def test_one_layout_box_never_solidifies_the_white_gap_between_its_atoms() -> None:
    """Large-panel scanline solidify is an interior repair, not a cross-atom bridge."""
    detection_settings = mask.normalize_settings({
        "min_element_area": 10,
        "component_padding_px": 0,
    })
    with tempfile.TemporaryDirectory() as temp_dir:
        slide_dir = Path(temp_dir) / "slide_001"
        slide_dir.mkdir(parents=True)
        image_path = slide_dir / "visual_draft.png"
        image = Image.new("RGB", (1200, 600), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((100, 100, 399, 499), fill="black")
        draw.rectangle((700, 100, 999, 499), fill="#2357A5")
        image.save(image_path)

        boxes = [_layout_box(90, 90, 920, 420)]
        detected = mask.detect_elements(
            image_path, slide_dir, detection_settings, layout_boxes=boxes
        )
        assert len(detected["elements"]) == 1
        element = detected["elements"][0]
        ink = 300 * 400 * 2
        assert element["source_ink_pixel_count"] == ink
        assert element["mask_pixel_count"] == ink, (
            "the union bbox is dense enough for solidify; the gap must stay unmasked"
        )
        assert element["atomic_component_ids"] == ["el_atom_0001", "el_atom_0002"]
        for run in element["mask_rle"]["runs"]:
            assert not (run[1] < 400 and run[2] > 699), run


def test_detection_cache_follows_image_settings_and_algorithm_version() -> None:
    detection_settings = mask.normalize_settings({
        "min_element_area": 10,
        "component_padding_px": 0,
    })
    cards = [_layout_box(15, 25, 100, 100), _layout_box(110, 25, 95, 100)]
    with tempfile.TemporaryDirectory() as temp_dir:
        slide_dir = Path(temp_dir) / "slide_001"
        image_path = _two_card_image(slide_dir)
        first = mask.detect_elements(image_path, slide_dir, detection_settings)
        assert first["cache_hit"] is False
        again = mask.detect_elements(image_path, slide_dir, detection_settings)
        assert again["cache_hit"] is True
        assert again["detection_settings_fingerprint"] == first["detection_settings_fingerprint"]

        # A different binding algorithm is a different pixel answer, so the v4
        # cache entry for the previous configuration must not be reused.
        rolled_back = mask.normalize_settings({
            "min_element_area": 10,
            "component_padding_px": 0,
            "layout_binding_v2": False,
        })
        stale_guard = mask.detect_elements(image_path, slide_dir, rolled_back)
        assert stale_guard["cache_hit"] is False
        assert stale_guard["detection_settings_fingerprint"] != first["detection_settings_fingerprint"]
        assert len(stale_guard["elements"]) == 1

        # The rollback arm keeps the old grouping failure visible: one closing
        # group is consumed by the first box that holds its centre, so the two
        # cards stay a single element.  Its Mask is still ink-only, because the
        # pixel-evidence switch is independent of the binding switch.
        v1 = mask.detect_elements(image_path, slide_dir, rolled_back, layout_boxes=cards)
        assert [element["element_id"] for element in v1["elements"]] == ["el_layout_001"]
        assert v1["elements"][0]["mask_pixel_count"] == 16198

        # Changing the layout boxes alone must also miss the cached answer.
        rebound = mask.detect_elements(image_path, slide_dir, detection_settings, layout_boxes=cards)
        assert rebound["cache_hit"] is False
        assert len(rebound["elements"]) == 2
        assert mask.detect_elements(
            image_path, slide_dir, detection_settings, layout_boxes=list(reversed(cards))
        )["cache_hit"] is True

        image = Image.open(image_path)
        ImageDraw.Draw(image).rectangle((250, 40, 300, 90), fill="#112233")
        image.save(image_path)
        assert mask.detect_elements(image_path, slide_dir, detection_settings)["cache_hit"] is False


def main() -> None:
    test_title_and_subtitle_fragments_follow_narrated_title_group()
    test_title_and_subtitle_use_distinct_narrated_groups_when_available()
    test_title_without_any_narration_remains_static_context()
    test_legacy_title_without_title_beat_never_falls_back_to_body_group()
    test_every_narrated_group_gets_an_independent_visual_anchor()
    test_existing_anchor_is_not_stolen_when_seeding_missing_group()
    test_nearby_icon_is_absorbed_by_closest_large_visual_island()
    test_volcengine_ai_mask_uses_provider_model_and_single_timeout_policy()
    test_semantic_object_match_expands_element_ids_without_model_guessing()
    safe_defaults = mask.normalize_settings({})
    assert safe_defaults["overwrite_existing_manual_mask"] is False
    assert safe_defaults["skip_locked_groups"] is True
    assert mask._confidence_level(0.9) == "high"
    assert mask._confidence_level(0.75) == "medium"
    assert mask._confidence_level(0.4) == "low"
    with tempfile.TemporaryDirectory() as temp_dir:
        slide_dir = Path(temp_dir) / "slide_001"
        slide_dir.mkdir(parents=True)
        image_path = slide_dir / "visual_draft.png"
        image = Image.new("RGB", (320, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((20, 30, 110, 120), fill="black")
        draw.rectangle((200, 40, 300, 130), fill="#2357A5")
        image.save(image_path)

        settings = mask.normalize_settings({
            "min_element_area": 10,
            "component_padding_px": 0,
            "overwrite_existing_manual_mask": True,
            "skip_locked_groups": False,
        })
        detected = mask.detect_elements(image_path, slide_dir, settings)
        assert detected["version"] == "auto_elements_v3_exact_rle_cached"
        assert detected["source_sha256"]
        assert detected["detection_settings_fingerprint"]
        assert mask.detect_elements(image_path, slide_dir, settings) == detected
        elements = detected["elements"]
        assert len(elements) == 2
        assert [item["element_id"] for item in elements] == ["el_auto_001", "el_auto_002"]
        assert (slide_dir / "auto_mask" / "elements" / "el_auto_001.png").exists()
        assert (slide_dir / "auto_mask" / "elements" / "el_auto_002.png").exists()
        assert all(item["mask_rle"]["encoding"] == "row_runs_v1" for item in elements)
        assert sum(mask._rle_pixel_count(item["mask_rle"]) for item in elements) == 91 * 91 + 101 * 91

        manifest_slide = {
            "slide_id": "slide_001",
            "groups": [],
            "semantic_blocks": [
                {"group_id": "semantic_left", "visual_group_id": "group_left", "box": [0, 0, 150, 170]},
                {"group_id": "semantic_right", "visual_group_id": "group_right", "box": [160, 0, 320, 170]},
            ],
        }
        fallback = mask._fallback_match(fixture_slide(), elements, manifest_slide)
        assert [item["group_id"] for item in fallback["matches"]] == ["group_left", "group_right"]
        assert fallback["unmatched_groups"] == []

        assert mask._find_group(manifest_slide["semantic_blocks"], "group_left")["group_id"] == "semantic_left"

        cleaned = mask._clean_match(
            {
                "matches": [
                    {"group_id": "group_left", "narration_beat_id": "beat_left", "element_ids": ["el_auto_001"], "confidence": 0.9},
                    {"group_id": "group_right", "narration_beat_id": "beat_right", "element_ids": ["el_auto_001"], "confidence": 0.9},
                ]
            },
            fixture_slide(),
            elements,
            settings,
            fallback,
        )
        assert len(cleaned["matches"]) == 1
        assert cleaned["unmatched_groups"] == ["group_right"]

        completed = mask._complete_component_coverage(fallback, detected)
        assert completed["quality"]["passed"] is True
        assert completed["quality"]["foreground_coverage_ratio"] == 1.0
        assert completed["quality"]["minimum_foreground_coverage_ratio"] == 0.995
        assert completed["quality"]["overlap_pixel_count"] == 0
        assert completed["unmatched_elements"] == []

        cross_region = {
            "canvas": {"width": 320, "height": 180},
            "elements": [
                _mask_element("wide_left", 5, 80, 30, 20),
                _mask_element("wide_right", 285, 80, 30, 20),
            ],
            "residual_elements": [],
        }
        cross_completed = mask._complete_component_coverage(
            {
                "matches": [{"group_id": "wide_flow", "element_ids": ["wide_left", "wide_right"], "confidence": 0.95}],
                "unmatched_groups": [],
            },
            cross_region,
        )
        assert cross_completed["quality"]["passed"] is True
        assert not cross_completed["semantic_quality"]["blocking_errors"]
        assert any(
            warning.get("type") == "group_crosses_left_and_right_regions"
            for warning in cross_completed["semantic_quality"]["warnings"]
        )

        forced_completion = {
            "canvas": {"width": 320, "height": 180},
            "elements": [
                _mask_element("left_anchor", 20, 80, 30, 20),
                _mask_element("right_anchor", 270, 80, 30, 20),
                _mask_element("left_extra", 55, 82, 12, 12),
            ],
            "residual_elements": [],
        }
        forced_completed = mask._complete_component_coverage(
            {
                "matches": [
                    {"group_id": "left", "element_ids": ["left_anchor"], "confidence": 0.95},
                    {"group_id": "right", "element_ids": ["right_anchor"], "confidence": 0.95},
                ],
                "unmatched_groups": [],
            },
            forced_completion,
        )
        assert forced_completed["quality"]["foreground_coverage_ratio"] == 1.0
        assert forced_completed["quality"]["unassigned_component_count"] == 0
        left_match = next(item for item in forced_completed["matches"] if item["group_id"] == "left")
        assert "left_extra" in left_match["element_ids"]

        manifest = {"slides": [manifest_slide]}
        applied = mask._apply(manifest, fixture_slide(), detected, completed, settings)
        assert applied["updated"] == 2
        assert len(manifest_slide["groups"]) == 2
        assert {group["visual_group_id"] for group in manifest_slide["groups"]} == {"group_left", "group_right"}
        colors = {group["manual_mask"]["color"] for group in manifest_slide["groups"]}
        assert len(colors) == 2
        assert all(group["manual_mask"]["source"] == "ai_auto_mask_v3_exact_rle" for group in manifest_slide["groups"])
        assert all(group["manual_mask"]["rle"]["runs"] for group in manifest_slide["groups"])
        assert all(group["manual_mask"]["strokes"] == [] for group in manifest_slide["groups"])
        assert all(group["review_status"] == "ai_matched" for group in manifest_slide["groups"])
        assert all(group["reveal"]["type"] == "crop_fade_up" for group in manifest_slide["groups"])
        assert all(group["reveal"]["duration"] == 0.25 for group in manifest_slide["groups"])
        alphas = [
            np.asarray(manual_mask_alpha(group["manual_mask"], 320, 180)) > 0
            for group in manifest_slide["groups"]
        ]
        assert not np.any(alphas[0] & alphas[1])

        review_payload = {
            "matches": [
                {"group_id": "group_left", "confidence": 0.78},
                {"group_id": "group_right", "confidence": 0.92},
            ],
            "unmatched_groups": ["group_missing"],
        }
        issues = mask._review_issues(review_payload)
        assert [issue["group_id"] for issue in issues] == ["group_left", "group_missing"]
        assert issues[0]["confidence_level"] == "medium"

        protected_group = manifest_slide["groups"][0]
        protected_group["manual_mask"]["source"] = "manual_paint"
        protected_group["manual_mask"]["strokes"] = [
            {"mode": "paint", "size": 8, "points": [{"x": 30, "y": 30}]}
        ]
        protected_before = json.dumps(protected_group["manual_mask"], sort_keys=True)
        mask._apply(manifest, fixture_slide(), detected, completed, settings)
        assert json.dumps(protected_group["manual_mask"], sort_keys=True) == protected_before

        duplicate_candidate_slide = {
            "slide_id": "slide_001",
            "groups": [],
            "semantic_blocks": [],
        }
        duplicate_candidate_payload = {
            **completed,
            "matches": [
                {
                    "group_id": "group_left",
                    "element_ids": [],
                    "confidence": 0.7,
                    "below_threshold": True,
                },
                *completed["matches"],
            ],
        }
        duplicate_applied = mask._apply(
            {"slides": [duplicate_candidate_slide]},
            fixture_slide(),
            detected,
            duplicate_candidate_payload,
            settings,
        )
        assert duplicate_applied == {"updated": 2, "skipped": 0}

        corrected = dict(manifest_slide["groups"][0]["manual_mask"])
        corrected["strokes"] = [
            {"mode": "erase", "eraser": True, "size": 12, "points": [{"x": 50, "y": 50}]},
            {"mode": "paint", "eraser": False, "size": 8, "points": [{"x": 150, "y": 150}]},
        ]
        corrected_alpha = np.asarray(manual_mask_alpha(corrected, 320, 180))
        assert corrected_alpha[50, 50] == 0
        assert corrected_alpha[150, 150] == 255

        complete_with_decorative_warnings = {
            "complete": True,
            "processed_slide_count": 1,
            "updated_group_count": 2,
            "warnings": ["装饰元素未关联口播"],
            "slides": [{"slide_id": "slide_001", "unmatched_group_count": 0, "warnings": ["装饰元素未匹配"]}],
        }
        assert one_click._ai_mask_quality_errors(complete_with_decorative_warnings, 2) == []
        broken_pixel_quality = {
            "complete": True,
            "processed_slide_count": 1,
            "updated_group_count": 2,
            "slides": [{
                "slide_id": "slide_001",
                "unmatched_group_count": 0,
                "quality": {
                    "passed": False,
                    "foreground_coverage_ratio": 0.91,
                    "overlap_pixel_count": 120,
                    "unassigned_component_count": 3,
                },
            }],
        }
        pixel_errors = one_click._ai_mask_quality_errors(broken_pixel_quality, 2)
        assert len(pixel_errors) == 1
        assert "91.00%" in pixel_errors[0] and "120" in pixel_errors[0] and "3" in pixel_errors[0]
        pipeline_source = inspect.getsource(one_click._run_pipeline)
        assert "pipeline_service_factory" in pipeline_source
        assert "server_module" not in pipeline_source
        assert "services.save_narration" in pipeline_source
        assert "TestClient" not in pipeline_source

    print("AI Mask automation checks passed")


if __name__ == "__main__":
    main()
