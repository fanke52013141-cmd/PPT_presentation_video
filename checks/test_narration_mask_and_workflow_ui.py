import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
import server

from scripts.write_narration_from_visual_contract import build_slide_narration
from server import (
    dedupe_narration_beats,
    narration_dedupe_key,
    normalize_narration_segments,
    normalize_slide_script_plan,
    normalize_slide_visual_plan,
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


def test_step2_script_plan_normalizes_to_minimal_step_a_contract():
    plan = normalize_slide_script_plan(
        {
            "title": "测试",
            "slides": [
                {
                    "slide_id": "slide_001",
                    "slide_title": "第一页",
                    "slide_subtitle": "副标题",
                    "body": "旧正文字段",
                    "body_points": [{"text": "旧要点"}],
                    "narration": "这是完整演讲稿。",
                    "narration_segments": [{"narration": "旧分段"}],
                }
            ],
        },
        "测试",
    )
    assert set(plan["slides"][0]) == {"slide_id", "slide_title", "narration"}
    assert "副标题" not in json.dumps(plan, ensure_ascii=False)
    visual_input = json.loads(server.build_step2_visual_user_prompt(plan))["slide_script_plan"]
    assert visual_input == plan


def test_step2_visual_element_normalization_does_not_silently_delete_duplicate_text():
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
    assert [item["narration"] for item in elements] == ["同一段旁白。", "同一段旁白！"]


def test_step2_visual_plan_requires_one_to_one_complete_narration_mapping():
    script_plan = {
        "title": "测试",
        "slides": [
            {
                "slide_id": "slide_001",
                "slide_title": "第一页",
                "narration": "先介绍本页主题。再讲正文内容。",
            }
        ],
    }
    valid = normalize_slide_visual_plan(
        {
            "slides": [
                {
                    "slide_id": "slide_001",
                    "visual_elements": [
                        {
                            "element_id": "el_001",
                            "role": "title",
                            "visual_type": "text",
                            "visual_description": "第一页",
                            "narration": "先介绍本页主题。",
                        },
                        {
                            "element_id": "el_002",
                            "role": "body",
                            "visual_type": "picture",
                            "visual_description": "一个连续的正文画面",
                            "narration": "再讲正文内容。",
                        },
                    ],
                }
            ]
        },
        script_plan,
    )
    assert len(valid["slides"][0]["visual_elements"]) == 2

    invalid = json.loads(json.dumps(valid, ensure_ascii=False))
    invalid["slides"][0]["visual_elements"][0]["narration"] = ""
    with pytest.raises(HTTPException, match="没有对应演讲片段"):
        normalize_slide_visual_plan(invalid, script_plan)


def test_step2_visual_plan_rejects_separate_subtitle_element():
    script_plan = {
        "title": "测试",
        "slides": [{"slide_id": "slide_001", "slide_title": "标题", "narration": "先讲标题。再讲正文。"}],
    }
    with pytest.raises(HTTPException, match="只能包含 title 和 body"):
        normalize_slide_visual_plan(
            {
                "slides": [
                    {
                        "slide_id": "slide_001",
                        "visual_elements": [
                            {"element_id": "el_001", "role": "title", "visual_type": "text", "visual_description": "标题", "narration": "先讲标题。"},
                            {"element_id": "el_002", "role": "subtitle", "visual_type": "text", "visual_description": "副标题", "narration": ""},
                            {"element_id": "el_003", "role": "body", "visual_type": "text", "visual_description": "正文", "narration": "再讲正文。"},
                        ],
                    }
                ]
            },
            script_plan,
        )


def test_default_step2_prompts_explicitly_forbid_duplicate_narration_binding():
    script_prompt = (ROOT / "templates" / "prompts" / "step2_script_system.md").read_text(encoding="utf-8")
    visual_prompt = (ROOT / "templates" / "prompts" / "step2_visual_system.md").read_text(encoding="utf-8")
    assert "一项信息只讲一次" in script_prompt
    assert "一个片段只绑定一个元素" in visual_prompt
    assert "不得重复、遗漏或改写" in visual_prompt
    assert "一个元素也只能绑定一个片段" in visual_prompt
    assert "每个 `narration` 都必须非空" in visual_prompt


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
    assert "grid-template-columns: repeat(3, 54px)" in css
    assert "#step3-btn-batch-generate," in css
    assert ".step3-ai-action," in css
    assert "background: #ffffff !important" in css
    assert "white-space: nowrap !important" in css


def test_builtin_prompts_and_mask_state_are_reset_per_project():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    style_manager = (ROOT / "static" / "style_reference_manager_extension.js").read_text(encoding="utf-8")
    assert "正在编辑：" not in html
    assert "`「${slide.main_title}」`" not in app
    assert "setStep2GenerationStatus('');" in app
    assert "#step-panel-2 .slides-thumbnail-container" in css
    assert "resetStep5ProjectState();" in app
    assert "manifestProjectId !== projectId" in app
    assert "renderStep2PromptTemplateOptions('');" in app
    assert "template.prompt_type === state.activeStep2PromptMode && template.built_in" not in app
    assert "selectedTemplateId: 'handdrawn'" in style_manager
    assert "STATE.selectedTemplateId = builtInDefault ? String(builtInDefault.id) : 'current'" in style_manager


def test_workflow_rail_owns_toasts_and_disabled_buttons_remain_readable():
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "body.workspace-open #toast-container" in css
    assert "left: 18px" in css
    assert "#step6-btn-audio-confirm-next:disabled" in css
    assert "#step8-btn-render:disabled" in css


def test_workflow_connector_stops_at_step_six_and_step2_errors_are_visible():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    assert "sidebar-flow-title" not in html
    assert "left: 30.875px" in css
    assert "repeating-linear-gradient" in css
    assert "height: calc((64px + 0.35rem) * 5)" in css
    assert "step2-generation-status" in html
    assert "setStep2GenerationStatus" in app
    assert "Step 2 generation failed" in app


def test_step2_timeout_is_logged_and_returned_as_actionable_error(monkeypatch, tmp_path):
    assert server.STEP2_LLM_TIMEOUT_SEC == 240.0

    class FakeCompletions:
        def create(self, **kwargs):
            raise TimeoutError("simulated upstream timeout")

    class FakeClient:
        def __init__(self):
            self.chat = SimpleNamespace(completions=FakeCompletions())
            self.closed = False

        def close(self):
            self.closed = True

    client = FakeClient()
    monkeypatch.setattr(
        server,
        "configured_step2_llm",
        lambda: ("test-key", "https://example.invalid/v1", "test-model", 0.2, 2048),
    )
    monkeypatch.setattr(server, "get_openai_client", lambda **kwargs: client)
    project = SimpleNamespace(id="project-test", run_dir=str(tmp_path))

    with pytest.raises(HTTPException) as exc_info:
        server.run_step2_json_llm(
            project=project,
            system_prompt="system",
            user_prompt="user",
            artifact_prefix="step2_script_plan",
            schema_hint="{}",
            trace_id="trace123",
        )

    assert exc_info.value.status_code == 504
    assert "240" in str(exc_info.value.detail)
    assert "Step 2A 演讲稿规划" in str(exc_info.value.detail)
    assert client.closed is True
    records = [json.loads(line) for line in (tmp_path / "logs" / "pipeline.log").read_text(encoding="utf-8").splitlines()]
    assert records[-1]["event"] == "step2_script_plan_failed"
    assert records[-1]["timeout"] is True


def test_doubao_step2_requests_disable_deep_thinking():
    assert server.step2_llm_vendor_options(
        "doubao-seed-2-1-turbo-260628",
        "https://ark.cn-beijing.volces.com/api/v3",
    ) == {"extra_body": {"thinking": {"type": "disabled"}}}
    assert server.step2_llm_vendor_options("gpt-4.1", "https://api.openai.com/v1") == {}
