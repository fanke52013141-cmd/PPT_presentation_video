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
