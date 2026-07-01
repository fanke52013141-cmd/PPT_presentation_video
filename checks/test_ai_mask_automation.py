"""Focused checks for automatic AI Mask detection and mapping."""

import tempfile
from pathlib import Path
import sys
import os
import inspect

from PIL import Image, ImageDraw
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime_ai_mask as mask
from scripts.build_reveal_scene import manual_mask_alpha
os.environ.setdefault("PPT_STUDIO_DISABLE_ONE_CLICK_ORCHESTRATOR", "1")
import runtime_one_click_orchestrator as one_click


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


def test_title_and_subtitle_fragments_merge_by_narration():
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
    assert consolidated["title_region_policy"] == "single_mask_by_narration"
    assert set(consolidated["forced_element_owners"]) == {"title_a", "title_b", "subtitle_a", "subtitle_b"}
    assert set(consolidated["forced_element_owners"].values()) == {"opening"}
    completed = mask._complete_component_coverage(consolidated, elements)
    matches = {item["group_id"]: set(item["element_ids"]) for item in completed["matches"]}
    assert matches["opening"] == {"title_a", "title_b", "subtitle_a", "subtitle_b"}
    assert matches["body_group"] == {"body"}
    assert completed["quality"]["passed"] is True


def test_title_and_subtitle_stay_separate_for_distinct_narration():
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
    assert consolidated["title_region_policy"] == "separate_masks_by_narration"
    owners = consolidated["forced_element_owners"]
    assert owners["title_a"] == owners["title_b"] == "title_group"
    assert owners["subtitle_a"] == owners["subtitle_b"] == "subtitle_group"


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
    assert set(owners.values()) == {"opening", "image_group", "summary_group"}


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


def test_volcengine_ai_mask_uses_provider_model_and_single_timeout_policy():
    resolved, configured = mask._resolved_vision_model(_FakeVisionSettings)
    assert resolved == "doubao-seed-2-1-turbo-260628"
    assert configured == "gpt-4o"
    source = inspect.getsource(mask._vision_match)
    assert "step2_llm_vendor_options" in source
    assert "AI_MASK_VISION_TIMEOUT_SEC" in source
    assert "if _is_timeout(server_module, exc)" in source


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


def main() -> None:
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
        assert completed["quality"]["overlap_pixel_count"] == 0
        assert completed["unmatched_elements"] == []

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
        alphas = [
            np.asarray(manual_mask_alpha(group["manual_mask"], 320, 180)) > 0
            for group in manifest_slide["groups"]
        ]
        assert not np.any(alphas[0] & alphas[1])

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
        assert 'client.put(f"/api/projects/{project_id}/steps/6/result"' in pipeline_source

    print("AI Mask automation checks passed")


if __name__ == "__main__":
    main()
