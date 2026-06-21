#!/usr/bin/env python3
"""Regression checks for configurable storyboard roles and Mask animations."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.build_reveal_scene import build_event
from scripts.build_remotion_props import read_subtitle_style
from scripts.pipeline_profiles import allowed_reveal_actions, read_pipeline_profile, role_catalog
from scripts.validate_visual_contract import validate_contract


def main() -> None:
    profile = read_pipeline_profile()
    roles = role_catalog(profile)
    assert roles["title"]["required"] is True
    assert roles["subtitle"]["required"] is False
    assert roles["summary"]["required"] is False
    assert {"quote", "data_point", "process_step", "callout"} <= set(roles)

    required_actions = {
        "wipe_left_to_right",
        "scratch_reveal",
        "brush_wipe_left_to_right",
        "sticker_pop",
        "stamp_in",
        "paper_drop",
    }
    assert required_actions <= allowed_reveal_actions(profile)
    for role, reveal in profile["reveal"]["default_by_role"].items():
        assert reveal["type"] == "wipe_left_to_right", f"{role} default reveal is not uniform"

    event = build_event(
        "slide_001",
        {
            "id": "callout_group",
            "reveal": {
                "type": "sticker_pop",
                "duration": 0.7,
                "rotation": -4,
            },
        },
        "layer_callout",
        0.2,
    )
    assert event["action"] == "sticker_pop"
    assert event["duration"] == 0.7
    assert event["params"]["rotation"] == -4

    subtitle_contract = {
        "version": "visual_contract_v1",
        "slides": [
            {
                "slide_id": "slide_001",
                "main_title": "标题",
                "visual_groups": [
                    {
                        "id": "subtitle_group",
                        "role": "subtitle",
                        "visible_text": "需要朗读的副标题",
                        "visual_anchor": "副标题位置",
                        "narration_function": "补充解释",
                        "content_unit_id": "subtitle_unit",
                        "speak_policy": "speak",
                        "mask_target": "副标题整体",
                    }
                ],
                "narration_beats": [
                    {
                        "id": "subtitle_beat",
                        "group_id": "subtitle_group",
                        "content_unit_id": "subtitle_unit",
                        "visible_anchor": "需要朗读的副标题",
                        "spoken_intent": "朗读副标题",
                        "spoken_text": "需要朗读的副标题。",
                    }
                ],
            }
        ],
    }
    assert validate_contract(subtitle_contract, min_groups=1, max_groups=8, profile=profile) == 1

    with tempfile.TemporaryDirectory() as temp_dir:
        run_dir = Path(temp_dir)
        (run_dir / "visual_settings.json").write_text(
            json.dumps(
                {
                    "subtitle_style": {
                        "font_key": "noto_serif_sc",
                        "font_family": "Noto Serif SC",
                        "font_size": 46,
                        "bottom": 60,
                    }
                }
            ),
            encoding="utf-8",
        )
        subtitle_style = read_subtitle_style(run_dir)
        assert subtitle_style["font_key"] == "noto_serif_sc"
        assert subtitle_style["font_size"] == 46
        assert subtitle_style["bottom"] == 60

    for schema_name in ("reveal_manifest.schema.json", "animation_timeline.schema.json"):
        schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8-sig"))
        schema_text = json.dumps(schema, ensure_ascii=False)
        for action in required_actions:
            assert action in schema_text, f"{action} missing from {schema_name}"

    print("generalized storyboard and animation checks passed")


if __name__ == "__main__":
    main()
