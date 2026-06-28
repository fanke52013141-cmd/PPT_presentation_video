#!/usr/bin/env python3
"""Regression checks for prompt-based Step 2/style settings and unified animation UI."""

from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_reveal_scene import build_event  # noqa: E402
from scripts.pipeline_profiles import normalize_reveal_action, role_catalog  # noqa: E402
import server as server_module  # noqa: E402
from server import (  # noqa: E402
    OPEN_SOURCE_CHINESE_FONTS,
    apply_storyboard_profile_patch,
    image_style_template_detail,
    list_storyboard_templates,
    merge_image_style_update,
    parse_storyboard_profile_text,
    read_style_tokens_data,
    storyboard_profile_editor_data,
)

def main() -> None:
    profile_text = (ROOT / "config" / "pipeline_profiles.yaml").read_text(encoding="utf-8-sig")
    profile = parse_storyboard_profile_text(profile_text)
    editor = storyboard_profile_editor_data(profile)
    assert set(editor["roles"]["subtitle"]) == {"label", "description", "enabled"}
    assert "visual_groups[].content_unit_id" in editor["protected_fields"]

    patched = apply_storyboard_profile_patch(
        profile,
        {
            "slide_count": {"short_article": "5-7"},
            "roles": {
                "subtitle": {
                    "enabled": False,
                }
            },
        },
    )
    assert patched["storyboard"]["slide_count"]["short_article"] == "5-7"
    assert "subtitle" not in role_catalog(patched)
    assert "required" not in patched["storyboard"]["roles"]["subtitle"]
    assert "speak_policy" not in patched["storyboard"]["roles"]["subtitle"]
    assert storyboard_profile_editor_data(patched)["roles"]["subtitle"]["enabled"] is False

    migrated = server_module.sanitize_storyboard_profile(
        {
            "storyboard": {
                "roles": {
                    "subtitle": {
                        "label": "副标题",
                        "required": False,
                        "speak_policy": "display_only",
                        "description": "可选副标题；如果页面不需要，就不要生成。",
                    },
                    "decoration": {
                        "label": "装饰",
                        "description": "不承载语义、不绑定旁白的装饰元素。",
                    },
                },
                "structure_rules": [
                    "每个可讲解的 visual_group 必须至少有一个 narration_beat 绑定；display_only 组不要绑定旁白。"
                ],
            }
        }
    )
    assert "required" not in migrated["storyboard"]["roles"]["subtitle"]
    assert "speak_policy" not in migrated["storyboard"]["roles"]["subtitle"]
    assert "可选副标题" not in migrated["storyboard"]["roles"]["subtitle"]["description"]
    assert "不绑定旁白" not in migrated["storyboard"]["roles"]["decoration"]["description"]
    assert all("display_only" not in rule for rule in migrated["storyboard"]["structure_rules"])

    contract = server_module.normalize_visual_contract(
        {
            "version": "visual_contract_v1",
            "slides": [
                {
                    "slide_id": "slide_001",
                    "visual_groups": [
                        {
                            "id": "spoken_group",
                            "role": "content_body",
                            "visible_text": "讲解内容",
                            "visual_anchor": "左侧内容区",
                            "narration_function": "讲解主要内容",
                            "content_unit_id": "spoken_unit",
                            "speak_policy": "speak",
                        },
                        {
                            "id": "visual_only_group",
                            "role": "callout",
                            "visible_text": "画面提示",
                            "visual_anchor": "右侧提示区",
                            "narration_function": "提供视觉提示",
                            "content_unit_id": "visual_only_unit",
                            "speak_policy": "display_only",
                        },
                    ],
                    "narration_beats": [
                        {
                            "id": "beat_01",
                            "group_id": "spoken_group",
                            "content_unit_id": "spoken_unit",
                            "visible_anchor": "讲解内容",
                            "spoken_intent": "讲解",
                            "spoken_text": "讲解内容。",
                        }
                    ],
                }
            ],
        }
    )
    slide = contract["slides"][0]
    assert len(slide["narration_beats"]) == 1
    assert all("speak_policy" not in group for group in slide["visual_groups"])
    semantic_blocks = server_module.deterministic_semantic_blocks("slide_001", slide, None)
    assert {block["visual_group_id"] for block in semantic_blocks} == {"spoken_group"}
    assert normalize_reveal_action("scratch_reveal", profile, for_renderer=True) == "scratch_reveal"
    assert normalize_reveal_action("brush_wipe_left_to_right", profile, for_renderer=True) == "brush_wipe_left_to_right"
    scratch_event = build_event(
        "slide_001",
        {"id": "group_01", "reveal": {"type": "scratch_reveal", "duration": 0.9}},
        "group_01_layer",
        0.5,
    )
    assert scratch_event["action"] == "scratch_reveal"

    style = read_style_tokens_data()
    merged = merge_image_style_update(
        style,
        {
            "brand": {"style_keywords": ["中国水墨", "留白"]},
            "visual_assets": {
                "image_style": "chinese_ink",
                "layout_rules": ["每个语块独立留白"],
                "avoid": ["复杂背景"],
            },
        },
    )
    assert merged["brand"]["name"] == style["brand"]["name"]
    assert merged["brand"]["style_keywords"] == ["中国水墨", "留白"]
    assert merged["visual_assets"]["reveal_friendly_layout"] == ["每个语块独立留白"]
    assert merged["canvas"]["background"] == "#FFFFFF"

    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    app_js = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    css = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    step2_visual_prompt = (ROOT / "templates" / "prompts" / "step2_visual_system.md").read_text(encoding="utf-8")
    assert 'id="step5-btn-animation-settings"' in html
    assert 'id="modal-animation-settings"' in html
    assert 'id="subtitle-font-weight"' in html
    assert 'id="step2-btn-script-prompt"' in html
    assert 'id="step2-btn-visual-prompt"' in html
    assert 'id="step2-script-system-prompt"' in html
    assert 'id="step2-script-output-example"' in html
    assert 'id="step2-visual-system-prompt"' in html
    assert 'id="step2-visual-output-example"' in html
    assert 'id="step2-slide-title-input"' in html
    assert 'id="step2-slide-subtitle-input"' in html
    assert 'id="step2-slide-body-input"' in html
    assert 'id="step2-slide-narration-input"' in html
    assert 'style_reference_manager_extension.js' in html
    assert 'id="modal-step2-generate"' in html
    assert 'id="step2-generation-requirement"' in html
    assert 'id="subtitle-safe-width-guide"' in html
    for removed_token in [
        'storyboard-template-select',
        'storyboard-rules-input',
        'storyboard-profile-input',
        'storyboard-schema-input',
        'btn-storyboard-rules-ai-draft',
        'btn-image-style-ai-draft',
        'image-style-use-advanced',
        'image-style-validation-status',
        'step2-groups-list',
    ]:
        assert removed_token not in html
    assert "mask-animation-card" not in app_js
    for removed_token in [
        "generateStoryboardRulesAiDraft",
        "generateImageStyleAiDraft",
        "applyStoryboardAiDraft",
        "discardStoryboardAiDraft",
        "applyImageStyleAiDraft",
        "discardImageStyleAiDraft",
        "storyboardRoleOptions",
        "addVisualGroup",
        "source_segment_id",
        "rules/ai-draft",
        "image-style/ai-draft",
    ]:
        assert removed_token not in app_js
    assert "source_segment_id" not in step2_visual_prompt
    assert "不要输出 text" in step2_visual_prompt
    assert "visual_type 与 visual_description 已经足够表达画面内容" in step2_visual_prompt
    assert server_module.IMAGE_STYLE_PROMPT_KEY == "prompt_system_content"
    assert "previewGlobalAnimationSettings" in app_js
    assert ".config-editor-scroll" in css
    assert ".mask-visual-card" in css
    assert ".ai-draft-status" not in css
    assert ".ai-request-panel" not in css
    assert ".ai-draft-preview" not in css
    route_paths = [getattr(route, "path", "") for route in server_module.app.routes]
    assert route_paths.count("/api/projects/{project_id}/steps/2/prompts") == 2
    assert "/api/projects/{project_id}/steps/2/rules/ai-draft" not in route_paths
    assert "/api/projects/{project_id}/steps/3/image-style/ai-draft" not in route_paths
    assert list_storyboard_templates()[0]["id"] == "default"
    assert image_style_template_detail("default")["references"]["template"]["exists"]
    font_keys = {font["key"] for font in OPEN_SOURCE_CHINESE_FONTS}
    assert {"lxgw_marker_gothic", "lxgw_wenkai_tc", "noto_sans_tc", "noto_serif_tc"} <= font_keys

    original_paths = {
        key: getattr(server_module, key)
        for key in (
            "STORYBOARD_TEMPLATES_PATH",
            "STYLE_TOKENS_PATH",
            "STYLE_REFERENCE_DIR",
            "IMAGE_STYLE_TEMPLATES_DIR",
            "IMAGE_STYLE_TEMPLATES_INDEX",
        )
    }
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            server_module.STORYBOARD_TEMPLATES_PATH = str(temp_root / "storyboard_templates.json")
            saved_storyboard = server_module.save_storyboard_template(
                {
                    "name": "回归分镜模板",
                    "rules": server_module.default_storyboard_rules(),
                    "profile_yaml": server_module.default_storyboard_profile_text(),
                    "profile_patch": {},
                }
            )
            assert saved_storyboard["template"]["name"] == "回归分镜模板"

            server_module.STYLE_TOKENS_PATH = str(temp_root / "active" / "style_tokens.yaml")
            server_module.STYLE_REFERENCE_DIR = str(temp_root / "active" / "references")
            server_module.IMAGE_STYLE_TEMPLATES_DIR = str(temp_root / "image_templates")
            server_module.IMAGE_STYLE_TEMPLATES_INDEX = str(temp_root / "image_templates" / "index.json")
            server_module.ensure_active_image_style_storage()
            saved_image = server_module.save_image_style_template({"name": "回归图片模板"})
            assert saved_image["template"]["references"]["template"]["exists"]
    finally:
        for key, value in original_paths.items():
            setattr(server_module, key, value)

    print("generalized settings checks passed")


if __name__ == "__main__":
    main()
