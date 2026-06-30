from pathlib import Path

from scripts.write_narration_from_visual_contract import build_slide_narration
from server import (
    dedupe_narration_beats,
    narration_dedupe_key,
    normalize_narration_segments,
    normalize_visual_contract,
    normalize_visual_elements,
)


ROOT = Path(__file__).resolve().parents[1]


def beat(beat_id: str, group_id: str, text: str) -> dict:
    return {
        "id": beat_id,
        "group_id": group_id,
        "content_unit_id": f"{group_id}_unit",
        "spoken_text": text,
    }


def group(group_id: str) -> dict:
    return {
        "id": group_id,
        "content_unit_id": f"{group_id}_unit",
        "visible_text": group_id,
        "role": "content_body",
    }


def test_narration_key_ignores_tts_markup_spacing_and_punctuation():
    assert narration_dedupe_key("<#0.5#> Token 的核心作用！") == narration_dedupe_key(
        "Token的核心作用。"
    )


def test_server_dedupe_keeps_first_spoken_sentence():
    beats = [
        beat("beat_01", "group_01", "同一句旁白。"),
        beat("beat_02", "group_02", "同一句旁白！"),
        beat("beat_03", "group_03", "新的旁白。"),
    ]
    result = dedupe_narration_beats(beats)
    assert [item["id"] for item in result] == ["beat_01", "beat_03"]


def test_visual_contract_normalization_removes_duplicate_beats():
    contract = {
        "slides": [
            {
                "slide_id": "slide_001",
                "visual_groups": [group("group_01"), group("group_02")],
                "narration_beats": [
                    beat("beat_01", "group_01", "保留这句。"),
                    beat("beat_02", "group_02", "保留这句！"),
                ],
            }
        ]
    }
    normalized = normalize_visual_contract(contract)
    assert [item["id"] for item in normalized["slides"][0]["narration_beats"]] == ["beat_01"]


def test_narration_writer_does_not_reintroduce_duplicates():
    slide = {
        "slide_id": "slide_001",
        "visual_groups": [group("group_01"), group("group_02")],
        "narration_beats": [
            beat("beat_01", "group_01", "只讲一次。"),
            beat("beat_02", "group_02", "只讲一次！"),
        ],
    }
    payload = build_slide_narration(slide, max_beat_chars=220)
    assert len(payload["beats"]) == 1
    assert payload["narration"] == "只讲一次。"


def test_step2_script_plan_normalization_removes_duplicate_segments():
    segments = normalize_narration_segments(
        [
            {"segment_id": "seg_001", "narration": "这条信息只讲一次。"},
            {"segment_id": "seg_002", "narration": "这条信息只讲一次！"},
            {"segment_id": "seg_003", "narration": "下一条新信息。"},
        ]
    )
    assert [item["segment_id"] for item in segments] == ["seg_001", "seg_003"]


def test_step2_visual_plan_keeps_only_one_binding_per_narration():
    elements = normalize_visual_elements(
        [
            {
                "element_id": "el_001",
                "role": "body",
                "visual_type": "text",
                "visual_description": "信息标题",
                "narration": "同一段旁白。",
            },
            {
                "element_id": "el_002",
                "role": "body",
                "visual_type": "illustration",
                "visual_description": "辅助插图",
                "narration": "同一段旁白！",
            },
        ]
    )
    assert [item["narration"] for item in elements] == ["同一段旁白。", ""]


def test_default_step2_prompts_explicitly_forbid_duplicate_narration_binding():
    script_prompt = (ROOT / "templates" / "prompts" / "step2_script_system.md").read_text(encoding="utf-8")
    visual_prompt = (ROOT / "templates" / "prompts" / "step2_visual_system.md").read_text(encoding="utf-8")
    assert "一项信息只讲一次" in script_prompt
    assert "最多只能被一个 visual_element 使用一次" in visual_prompt
    assert "所有非空 narration 必须两两不同" in visual_prompt


def test_mask_size_cursor_and_outline_contracts():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    assert 'id="step5-brush-size" type="range" min="100" max="200" value="140"' in html
    assert 'id="step5-eraser-size" type="range" min="100" max="200" value="100"' in html
    assert "toolSize * canvasRect.width / 1920" in app
    assert "const MASK_PREVIEW_OUTLINE_PX = 5" in app


def test_step3_actions_reserve_fixed_non_wrapping_slots():
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "step3-action-placeholder" in app
    assert "grid-template-columns: 48px 36px 36px" in css
    assert "white-space: nowrap !important" in css


def test_workflow_rail_owns_toasts_and_disabled_buttons_remain_readable():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "body.workspace-open #toast-container" in css
    assert "left: 18px" in css
    assert "#step6-btn-audio-confirm-next:disabled" in css
    assert "#step8-btn-render:disabled" in css
