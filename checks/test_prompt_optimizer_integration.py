from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import runtime_image_style_reverse as reverse_style
import runtime_project_profile as text_style
import runtime_project_style_references as style_references
import server
from scripts.write_visual_prompts import project_image_style_lines


def test_article_generation_uses_only_topic() -> None:
    assert "article_generation_v2_minimal" in server.DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT
    assert json.loads(server.build_article_generation_user_content("  测试主题  ")) == {"topic": "测试主题"}
    assert "project_name" not in server.DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT


def test_article_generation_migrates_only_legacy_default() -> None:
    original = server.get_setting
    try:
        server.get_setting = lambda key, default="": server.LEGACY_DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT_V1
        assert server.read_article_generation_system_content() == server.DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT
        server.get_setting = lambda key, default="": "CUSTOM ARTICLE PROMPT"
        assert server.read_article_generation_system_content() == "CUSTOM ARTICLE PROMPT"
    finally:
        server.get_setting = original


def test_narration_annotation_payload_is_minimal() -> None:
    incoming = {
        "slides": [{
            "slide_id": "slide_001",
            "beats": [{
                "id": "beat_001",
                "index": 9,
                "source_text": "旧旁白，不应复活。",
                "spoken_text": "旧旁白，不应复活。",
                "tts_text": "先解释 (REST) 概念，<#0.35#>再给出结论。",
                "visible_anchor": "不应发送",
                "group_id": "不应发送",
            }],
        }],
    }
    assert server.build_narration_annotation_input(incoming) == {
        "slides": [{
            "slide_id": "slide_001",
            "beats": [{"id": "beat_001", "source_text": "先解释 (REST) 概念，再给出结论。"}],
        }],
    }
    assert "narration_annotation_v2_minimal" in server.DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT
    assert server.narration_annotation_preserves_text(
        "先解释概念，<#0.35#>再给出结论。",
        "先解释概念，再给出结论。",
    )
    assert not server.narration_annotation_preserves_text(
        "先解释概念，<#0.35#>最后给出结论。",
        "先解释概念，再给出结论。",
    )
    assert server.clean_tts_text("保留 (REST) 和 (GraphQL)，移除 (breath) 与 <#0.3#>。") == (
        "保留 (REST) 和 (GraphQL)，移除 与 。"
    )
    assert server.normalize_minimax_tts_markup("说明 (REST) API。") == "说明 (REST) API。"


def test_step2_request_omits_stable_output_goal_and_empty_requirement() -> None:
    script_input = json.loads(server.build_step2_script_user_prompt(
        project_title="测试项目",
        article_content="# 文章\n正文",
        generation_requirement="",
    ))
    assert script_input == {"project_title": "测试项目", "article_content": "# 文章\n正文"}
    visual_input = json.loads(server.build_step2_visual_user_prompt({
        "title": "测试项目",
        "slides": [{"slide_id": "slide_001", "slide_title": "标题", "narration": "旁白"}],
    }))
    assert set(visual_input) == {"slide_script_plan"}
    assert "output_goal" not in json.dumps({"script": script_input, "visual": visual_input}, ensure_ascii=False)


def test_narration_annotation_migrates_legacy_builtins() -> None:
    original = server.get_setting
    values = {
        server.NARRATION_ANNOTATION_SYSTEM_CONTENT_KEY: server.LEGACY_DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT_V1,
        server.NARRATION_ANNOTATION_OUTPUT_EXAMPLE_KEY: server.LEGACY_DEFAULT_NARRATION_ANNOTATION_OUTPUT_EXAMPLE_V1,
    }
    try:
        server.get_setting = lambda key, default="": values.get(key, default)
        prompts = server.read_narration_annotation_prompts()
        assert prompts == (
            server.DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT,
            server.DEFAULT_NARRATION_ANNOTATION_OUTPUT_EXAMPLE,
        )
        values[server.NARRATION_ANNOTATION_SYSTEM_CONTENT_KEY] = "CUSTOM NARRATION PROMPT"
        assert server.read_narration_annotation_prompts()[0] == "CUSTOM NARRATION PROMPT"
    finally:
        server.get_setting = original


def test_reverse_style_prompt_and_user_input_are_minimal() -> None:
    assert "image_style_reverse_v2_minimal" in reverse_style.DEFAULT_REVERSE_SYSTEM_CONTENT
    assert reverse_style.build_reverse_style_user_text("") == ""
    assert json.loads(reverse_style.build_reverse_style_user_text("  保留圆角线条  ")) == {
        "requirement": "保留圆角线条"
    }
    example = json.loads(reverse_style.DEFAULT_REVERSE_OUTPUT_EXAMPLE)
    assert set(example) == {
        "style_name",
        "style_summary",
        "visual_language",
        "negative_prompt_rules",
        "sample_reference_image_prompts",
        "warnings",
    }
    assert "fixed_output_schema" not in reverse_style.build_reverse_style_user_text("保留圆角线条")
    assert reverse_style.validate_reverse_style_model_output(example) == example
    invalid = {**example, "system_content": "模型不应控制此字段"}
    try:
        reverse_style.validate_reverse_style_model_output(invalid)
    except ValueError as exc:
        assert "未声明字段" in str(exc)
    else:
        raise AssertionError("参考图反推接受了未声明字段")
    invalid_visual = {**example, "visual_language": {**example["visual_language"], "hidden_rule": "不应接受"}}
    try:
        reverse_style.validate_reverse_style_model_output(invalid_visual)
    except ValueError as exc:
        assert "visual_language 包含未声明字段" in str(exc)
    else:
        raise AssertionError("参考图反推接受了未声明的视觉字段")


def test_reverse_style_profile_builds_system_content_deterministically() -> None:
    style = reverse_style._style_with_required_rules(
        {
            "style_name": "线性风格",
            "style_summary": "圆角、轻盈。",
            "visual_language": {"line_style": "rounded"},
            "negative_prompt_rules": ["avoid ornate frames"],
            "sample_reference_image_prompts": ["A simple comparison scene."],
            "warnings": [],
        },
        [{"filename": "reference.png"}],
        "",
    )
    assert "Reusable visual style: 线性风格." in style["system_content"]
    assert "pure-white" not in style["system_content"]
    assert any("pure-white" in rule for rule in style["maskability_rules"])


def test_text_style_generation_compacts_optional_context() -> None:
    payload = json.loads(text_style.build_text_image_style_user_prompt(
        "柔和蓝紫",
        "面向职场新人",
        {
            "style_name": "旧风格",
            "system_content": "不应重复发送",
            "maskability_rules": ["不应重复发送"],
            "visual_language": {"line_style": "clean"},
        },
    ))
    assert payload == {
        "requirement": "柔和蓝紫",
        "project_context": "面向职场新人",
        "base_style": {
            "style_name": "旧风格",
            "visual_language": {"line_style": "clean"},
        },
    }
    assert "fixed_output_schema" not in json.dumps(payload, ensure_ascii=False)

    normalized = text_style.normalize_generated_image_style({
        "style_name": "安全风格",
        "style_summary": "简洁。",
        "visual_language": {"line_style": "clean"},
        "negative_prompt_rules": [],
        "sample_reference_image_prompts": [],
        "system_content": "模型注入的隐藏 System Content",
        "maskability_rules": ["模型注入的隐藏生产规则"],
        "reference_image_count_target": 1,
    })
    assert "模型注入" not in normalized["system_content"]
    assert "模型注入的隐藏生产规则" not in normalized["maskability_rules"]
    assert normalized["reference_image_count_target"] == 3


def test_step2_compatibility_endpoint_delegates_to_current_pipeline(monkeypatch) -> None:
    calls: list[tuple[str, object]] = []
    db = object()
    monkeypatch.setattr(server, "execute_step2_script_plan", lambda project_id, payload, session: calls.append(("script", payload)))
    monkeypatch.setattr(server, "execute_step2_visual_plan", lambda project_id, session: calls.append(("visual", session)))
    monkeypatch.setattr(
        server,
        "compose_step2_visual_contract",
        lambda project_id, session: {"success": True, "contract": {"slides": []}},
    )

    result = server.execute_step2("project_001", {}, db)

    assert calls == [("script", {}), ("visual", db)]
    assert result["success"] is True
    assert result["deprecated_route"] is True


def test_reference_image_prompt_has_no_fixed_group_count_or_duplicate_style() -> None:
    prompt = style_references._style_generation_prompt(
        "A simple comparison scene.",
        {
            "style_name": "线性风格",
            "style_summary": "圆角、轻盈。",
            "system_content": "STYLE SPECIFICATION ONCE",
            "negative_prompt_rules": [],
        },
        1,
    )
    assert prompt.count("STYLE SPECIFICATION ONCE") == 1
    assert "3-5" not in prompt
    assert "one coherent group is valid" in prompt
    assert len(style_references._reference_prompts({"sample_reference_image_prompts": ["One scene."]}, 3)) == 3
    style_lines = project_image_style_lines({
        "system_content": "AUTHORITATIVE STYLE ONCE",
        "style_summary": "must not be repeated",
        "sample_reference_image_prompts": ["must not be injected"],
        "maskability_rules": ["must not be duplicated"],
    })
    rendered_style = "\n".join(style_lines)
    assert rendered_style.count("AUTHORITATIVE STYLE ONCE") == 1
    assert "must not be repeated" not in rendered_style
    assert "must not be injected" not in rendered_style
    assert "must not be duplicated" not in rendered_style


def test_skill_policy_and_prompt_editor_are_wired() -> None:
    skill = (ROOT / ".agents" / "skills" / "optimize-prompts" / "SKILL.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    style_ui = (ROOT / "static" / "style_reference_manager_extension.js").read_text(encoding="utf-8")
    scene_prompt = (ROOT / "templates" / "prompts" / "scene_reconstruction.prompt.md").read_text(encoding="utf-8")
    assert "输入最小且必要" in skill
    assert ".agents/skills/optimize-prompts/SKILL.md" in agents
    assert "style-reverse" in app
    assert "btn-style-panel-reverse-prompt" in style_ui
    assert "/api/settings/image-style-reverse" in style_ui
    assert "/api/settings/image-style-reference-generation" in style_ui
    assert "btn-style-panel-reference-prompt" in style_ui
    assert "defaultStep2GenerationRequirement" not in app
    assert "syncStep6BeatText" in app
    assert "exact_rle_mask_with_manual_corrections_v5" in scene_prompt


def test_reverse_prompt_settings_routes_are_registered() -> None:
    routes = {
        (route.path, tuple(sorted(route.methods or [])))
        for route in server.app.routes
        if getattr(route, "path", "") == "/api/settings/image-style-reverse"
    }
    assert ("/api/settings/image-style-reverse", ("GET",)) in routes
    assert ("/api/settings/image-style-reverse", ("PUT",)) in routes

    reference_routes = {
        (route.path, tuple(sorted(route.methods or [])))
        for route in server.app.routes
        if getattr(route, "path", "") == "/api/settings/image-style-reference-generation"
    }
    assert ("/api/settings/image-style-reference-generation", ("GET",)) in reference_routes
    assert ("/api/settings/image-style-reference-generation", ("PUT",)) in reference_routes
