from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.style_agent import (  # noqa: E402
    StyleBundleError,
    build_style_bundle_user_prompt,
    bundle_prompt_preview,
    style_bundle_to_yaml,
    style_bundle_system_prompt,
    validate_style_bundle,
)


def sample_bundle():
    return {
        "name": "财经解释风",
        "description": "近白背景、深色线条、金色强调。",
        "style_data": {
            "brand": {
                "name": "Finance Explainer",
                "style_keywords": ["商业财经", "极简", "专业可信", "数据解释"],
            },
            "canvas": {"background": "#111111"},
            "colors": {
                "background": "#000000",
                "surface": "#FFFFFF",
                "ink": "#111111",
                "yellow": "#C8A64B",
            },
            "visual_assets": {
                "image_style": "business_flat_explainer",
                "diagram_style": "clean_finance_diagram",
                "reveal_friendly_layout": ["使用清晰解释结构。"],
                "avoid": ["深色整页背景"],
            },
        },
        "template_paste_words": {
            "title": "主题标题",
            "subtitle": "一句话解释核心问题",
            "groups": ["关键变量", "变化趋势", "因果链路", "最终结论"],
        },
        "example_paste_words": {
            "title": "市场为什么变化？",
            "subtitle": "用变量和链路解释现象",
            "groups": ["变量变化", "成本影响", "预期变化", "结果呈现"],
        },
        "template_image_prompt": "生成 1920x1080 的 PPT 模板参考图，纯白背景。",
        "example_image_prompt": "生成一张解释型 PPT 示例页。",
        "negative_prompt": "不要复杂 3D，不要乱码。",
    }


def test_style_bundle_prompt_and_normalization() -> None:
    system_prompt = style_bundle_system_prompt()
    assert "只输出合法 JSON" in system_prompt
    assert "style_bundle_v2_minimal" in system_prompt
    assert "不重复生产铁律" in system_prompt
    assert "不生成页面副标题" in system_prompt
    user_prompt = build_style_bundle_user_prompt(
        {"name": "财经解释风", "brief": "近白背景，专业简洁。"},
        "brand:\n  name: Base\n",
    )
    user_payload = json.loads(user_prompt)
    assert user_payload == {
        "requirement": "近白背景，专业简洁。",
        "name": "财经解释风",
        "base_style": "brand:\n  name: Base",
    }
    assert "fixed_output_schema" not in user_prompt
    assert "#FFFFFF" not in user_prompt

    normalized = validate_style_bundle(sample_bundle())
    style_data = normalized["style_data"]
    assert style_data["canvas"]["width"] == 1920
    assert style_data["canvas"]["height"] == 1080
    assert style_data["canvas"]["subtitle_reserved"] == {"y": 930, "height": 150}
    assert style_data["canvas"]["background"] == "#FFFFFF"
    assert style_data["colors"]["generated_image_background"] == "#FFFFFF"
    assert style_data["visual_assets"]["required_background"] == "flat_uniform_pure_white_generated_image"
    assert any("一个完整正文视觉组也是合法结果" in rule for rule in style_data["visual_assets"]["reveal_friendly_layout"])
    assert "subtitle" not in normalized["template_paste_words"]

    yaml_text = style_bundle_to_yaml(sample_bundle())
    assert "brand:" in yaml_text
    assert "subtitle_reserved:" in yaml_text

    preview = bundle_prompt_preview(sample_bundle())
    assert "template_image_prompt" in preview

def test_style_bundle_rejects_unknown_fields() -> None:
    bad_bundle = sample_bundle()
    bad_bundle["style_data"]["extra"] = {}
    try:
        validate_style_bundle(bad_bundle)
    except StyleBundleError:
        pass
    else:
        raise AssertionError("extra style_data key was accepted")



def main() -> None:
    test_style_bundle_prompt_and_normalization()
    test_style_bundle_rejects_unknown_fields()
    print("AI style bundle checks passed")


if __name__ == "__main__":
    main()
