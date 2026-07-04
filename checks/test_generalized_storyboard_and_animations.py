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
from scripts.bind_reveal_timeline import bind_slide
from scripts.pipeline_profiles import allowed_reveal_actions, read_pipeline_profile, role_catalog
from scripts.validate_visual_contract import validate_contract
import server as server_module


def main() -> None:
    profile = read_pipeline_profile()
    roles = role_catalog(profile)
    assert all("required" not in config for config in roles.values())
    assert all("speak_policy" not in config for config in roles.values())

    script_plan = {
        "title": "测试主题",
        "slides": [
            {
                "slide_id": "slide_001",
                "slide_title": "主标题",
                "slide_subtitle": "",
                "body_points": [{"point_id": "point_001", "text": "正文要点", "purpose": "讲解正文"}],
                "narration_segments": [{"segment_id": "seg_001", "narration": "这是演讲稿。", "purpose": "讲解"}],
            }
        ],
    }
    visual_plan = server_module.normalize_slide_visual_plan(
        {
            "slides": [
                {
                    "slide_id": "slide_001",
                    "visual_elements": [
                        {
                            "element_id": "el_001",
                            "role": "body",
                            "visual_type": "text",
                            "visual_description": "正文要点",
                            "narration": "这是演讲稿。",
                            "source_segment_id": "seg_001",
                            "text": "旧字段不应进入结果",
                        }
                    ],
                }
            ]
        }
    )
    element = visual_plan["slides"][0]["visual_elements"][0]
    assert set(element) == {"element_id", "role", "visual_type", "visual_description", "narration"}
    assert element["element_id"] == "el_001"
    assert element["visual_type"] == "text"
    assert element["visual_description"] == "正文要点"
    contract = server_module.compose_visual_contract_from_plans(script_plan, visual_plan, "test", "测试主题")
    group = contract["slides"][0]["visual_groups"][0]
    assert group["element_id"] == "el_001"
    assert group["visual_type"] == "text"
    semantic_block = server_module.deterministic_semantic_blocks("slide_001", contract["slides"][0], None)[0]
    assert semantic_block["element_id"] == "el_001"
    assert semantic_block["visual_type"] == "text"

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
        assert reveal["type"] == "crop_fade_up", f"{role} default reveal is not a whole-layer fade"
        assert reveal["duration"] == 0.25

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

    with tempfile.TemporaryDirectory() as temp_dir:
        slide_dir = Path(temp_dir)
        (slide_dir / "audio_timeline.json").write_text(
            json.dumps(
                {
                    "duration_sec": 6.0,
                    "audio_content_duration_sec": 6.0,
                    "segments": [
                        {"id": "seg_1", "start": 0.0, "end": 2.5, "text": "first"},
                        {"id": "seg_2", "start": 3.0, "end": 6.0, "text": "second"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (slide_dir / "animation_timeline.json").write_text(
            json.dumps(
                {
                    "events": [
                        {"target": "layer_1", "linked_segment_id": "seg_1", "action": "crop_fade_up", "duration": 0.25},
                        {"target": "layer_2", "linked_segment_id": "seg_2", "action": "crop_fade_up", "duration": 0.25},
                    ]
                }
            ),
            encoding="utf-8",
        )
        assert bind_slide(slide_dir, lead_sec=0.45, preserve_existing_at=False)
        bound_audio = json.loads((slide_dir / "audio_timeline.json").read_text(encoding="utf-8"))
        bound_animation = json.loads((slide_dir / "animation_timeline.json").read_text(encoding="utf-8"))
        assert bound_audio["audio_start_sec"] == 0.45
        assert [item["at"] for item in bound_animation["events"]] == [0.0, 3.0]
        assert [item["narration_start_at"] for item in bound_animation["events"]] == [0.45, 3.45]

    narration_authority_contract = {
        "version": "visual_contract_v1",
        "presentation_policy": {
            "subtitle_policy": "no_slides_have_subtitle",
            "subtitle_decided_by": "test",
        },
        "slides": [
            {
                "slide_id": "slide_001",
                "main_title": "标题",
                "visual_groups": [
                    {
                        "id": "subtitle_group",
                        "role": "subtitle",
                        "visible_text": "需要讲解的副标题",
                        "visual_anchor": "副标题位置",
                        "narration_function": "补充解释",
                        "content_unit_id": "subtitle_unit",
                        "mask_target": "副标题整体",
                    },
                    {
                        "id": "visual_only_group",
                        "role": "callout",
                        "visible_text": "画面提示",
                        "visual_anchor": "右侧提示区",
                        "narration_function": "仅提供视觉提示",
                        "content_unit_id": "visual_only_unit",
                        "mask_target": "右侧提示区整体",
                    }
                ],
                "narration_beats": [
                    {
                        "id": "subtitle_beat",
                        "group_id": "subtitle_group",
                        "content_unit_id": "subtitle_unit",
                        "visible_anchor": "需要讲解的副标题",
                        "spoken_intent": "讲解副标题",
                        "spoken_text": "需要讲解的副标题。",
                    }
                ],
            }
        ],
    }
    assert validate_contract(narration_authority_contract, min_groups=1, max_groups=8, profile=profile) == 1

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
