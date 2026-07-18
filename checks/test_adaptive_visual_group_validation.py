from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.pipeline_profiles import read_pipeline_profile
from scripts.validate_visual_contract import ContractError, validate_contract
import server


def make_contract(body_count: int = 1, *, body_has_narration: bool = True) -> dict:
    groups = [
        {
            "id": "title",
            "role": "title",
            "visible_text": "标题",
            "visual_anchor": "标题",
            "narration_function": "点题",
            "content_unit_id": "title_unit",
            "mask_target": "标题",
        }
    ]
    beats = [
        {
            "id": "title_beat",
            "group_id": "title",
            "content_unit_id": "title_unit",
            "visible_anchor": "标题",
            "spoken_intent": "点题",
            "spoken_text": "先看标题。",
        }
    ]
    for index in range(1, body_count + 1):
        group_id = f"body_{index}"
        unit_id = f"body_unit_{index}"
        groups.append(
            {
                "id": group_id,
                "role": "content_body",
                "visible_text": f"正文{index}",
                "visual_anchor": f"正文视觉{index}",
                "narration_function": f"解释正文{index}",
                "content_unit_id": unit_id,
                "mask_target": f"正文视觉岛{index}",
            }
        )
        if body_has_narration:
            beats.append(
                {
                    "id": f"body_beat_{index}",
                    "group_id": group_id,
                    "content_unit_id": unit_id,
                    "visible_anchor": f"正文{index}",
                    "spoken_intent": "解释正文",
                    "spoken_text": "这里讲解正文。",
                }
            )
    return {
        "version": "visual_contract_v1",
        "presentation_policy": {
            "subtitle_policy": "no_slides_have_subtitle",
            "visual_narration_mapping": "one_visual_element_to_one_narration_beat_v1",
        },
        "slides": [
            {
                "slide_id": "slide_001",
                "main_title": "标题",
                "visual_groups": groups,
                "narration_beats": beats,
            }
        ],
    }


def test_one_semantic_body_group_is_valid() -> None:
    assert validate_contract(make_contract(), 1, 10, read_pipeline_profile()) == 1


def test_one_group_cannot_describe_multiple_independent_visual_islands() -> None:
    contract = make_contract()
    contract["slides"][0]["visual_groups"][1]["visual_anchor"] = (
        "页面纵向排列四个独立的条件卡片，每张卡片表达不同约束。"
    )
    with pytest.raises(ContractError, match="describes multiple independent visual islands"):
        validate_contract(contract, 1, 10, read_pipeline_profile())


def test_unified_continuous_structure_remains_valid() -> None:
    contract = make_contract()
    contract["slides"][0]["visual_groups"][1]["visual_anchor"] = (
        "一个统一连续结构，在同一连续外框内排列四个步骤节点并整体 Reveal。"
    )
    assert validate_contract(contract, 1, 10, read_pipeline_profile()) == 1


def test_zero_body_groups_remains_invalid() -> None:
    with pytest.raises(ContractError, match="Expected at least 1 revealable visual group"):
        validate_contract(make_contract(body_count=0), 1, 10, read_pipeline_profile())


def test_title_only_narration_binding_is_invalid() -> None:
    with pytest.raises(ContractError, match="must have exactly one non-empty narration beat"):
        validate_contract(make_contract(body_has_narration=False), 1, 10, read_pipeline_profile())


def test_seven_groups_pass_without_an_arbitrary_common_range_warning(capsys: pytest.CaptureFixture[str]) -> None:
    contract = make_contract(body_count=7)
    assert validate_contract(contract, 1, 10, read_pipeline_profile()) == 1
    stderr = capsys.readouterr().err
    assert "common range" not in stderr
    assert "density guide" not in stderr


def test_more_than_density_guide_warns_but_remains_valid(capsys: pytest.CaptureFixture[str]) -> None:
    contract = deepcopy(make_contract(body_count=11))
    assert validate_contract(contract, 1, 10, read_pipeline_profile()) == 1
    assert "exceeds the configured density guide of 10" in capsys.readouterr().err


def test_step2_prompt_compatibility_detects_legacy_field_dependencies() -> None:
    assert server.step2_script_prompt_uses_legacy_contract(
        "body_points 必须包含屏幕要点；讲解分段要求如下"
    )
    assert server.step2_visual_prompt_uses_legacy_contract(
        "narration_segments[] 是视觉元素绑定口播的唯一依据；第 i 个 body_point 对应 seg_(i+1)"
    )
    defaults = server.default_step2_prompts()
    assert server.step2_prompt_compatibility(defaults) == {
        "contract_version": "step2_narration_visual_v5_speech_atomic",
        "script_prompt_legacy": False,
        "visual_prompt_legacy": False,
        "compatible": True,
    }
