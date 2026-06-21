"""Utilities for producing and validating AI-generated image style template bundles.

This module intentionally contains no FastAPI or database code. The server can call
these helpers to preview an AI style package, then later materialize it as a reusable
image-style template.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import yaml


STYLE_TOP_LEVEL_KEYS = ("brand", "canvas", "colors", "layout", "visual_assets")
VISUAL_ASSET_ALLOWED_KEYS = (
    "image_style",
    "diagram_style",
    "required_background",
    "reveal_friendly_layout",
    "avoid",
)
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
NEAR_WHITE_BACKGROUNDS = {"#FFFFFF", "#FFFDF7", "#FEFDF9"}


class StyleBundleError(ValueError):
    """Raised when an AI-generated style bundle is unsafe or malformed."""


def _as_dict(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise StyleBundleError(f"{field_name} must be an object")
    return copy.deepcopy(value)


def _string_list(value: Any, field_name: str, *, min_items: int = 0, max_items: int = 20) -> list[str]:
    if value is None:
        items: list[Any] = []
    elif isinstance(value, list):
        items = value
    else:
        raise StyleBundleError(f"{field_name} must be a list")
    result = [str(item).strip() for item in items if str(item).strip()]
    if len(result) < min_items:
        raise StyleBundleError(f"{field_name} must contain at least {min_items} item(s)")
    return result[:max_items]


def _normalize_hex(value: Any, field_name: str) -> str:
    text = str(value or "").strip().upper()
    if not HEX_COLOR_RE.fullmatch(text):
        raise StyleBundleError(f"{field_name} must be a #RRGGBB color")
    return text


def style_bundle_system_prompt() -> str:
    """Return the system prompt for asking an LLM to draft a style bundle."""

    return (
        "你是 PPT 视频图片风格设计代理。请把用户的风格需求转成一个可复用的图片风格模板包。"
        "只输出合法 JSON 对象，不要 Markdown。JSON 必须包含 name、description、style_data、"
        "template_paste_words、example_paste_words、template_image_prompt、example_image_prompt、negative_prompt。"
        "style_data 只能包含 brand、canvas、colors、layout、visual_assets。"
        "画布必须是 1920x1080、16:9，y=930 以下必须预留给视频字幕。"
        "背景必须是连续近白纯色，可用 #FFFFFF、#FFFDF7 或 #FEFDF9；禁止深色整页背景、纸纹、噪声、暗角、"
        "复杂 3D、赛博朋克、科技蓝黑大背景。所有贴词必须是简短中文。"
    )


def build_style_bundle_user_prompt(request: dict[str, Any], base_style_text: str = "") -> str:
    """Build a deterministic user prompt for the style-bundle LLM call."""

    name = str(request.get("name") or "").strip() or "未命名图片风格"
    brief = str(request.get("brief") or "").strip()
    audience = str(request.get("audience") or "普通观众").strip()
    sample_topic = str(request.get("sample_topic") or "为什么这个问题值得关注？").strip()
    base = base_style_text.strip()
    base_part = f"\n\n可参考的基础 style_tokens.yaml：\n{base}" if base else ""
    return (
        f"风格名称：{name}\n"
        f"风格需求：{brief}\n"
        f"目标受众：{audience}\n"
        f"示例主题：{sample_topic}\n\n"
        "请生成一个 AI 图片风格模板包。要求：\n"
        "1. style_data.brand.style_keywords 给出 6-10 个中文风格关键词。\n"
        "2. colors 使用 #RRGGBB，并保持近白背景。\n"
        "3. visual_assets.reveal_friendly_layout 必须包含字幕安全区、独立 visual group、边缘连续背景约束。\n"
        "4. template_paste_words.groups 必须是 4-8 个短中文占位词。\n"
        "5. example_paste_words 必须围绕示例主题，贴词能直接放进示例图。\n"
        "6. 两段 image_prompt 必须可直接用于生成 16:9 PPT 参考图。"
        f"{base_part}"
    )


def normalize_style_data(style_data: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the style_data section returned by the LLM."""

    raw = _as_dict(style_data, "style_data")
    unknown = sorted(set(raw) - set(STYLE_TOP_LEVEL_KEYS))
    if unknown:
        raise StyleBundleError(f"style_data has unsupported top-level keys: {', '.join(unknown)}")

    result = {key: copy.deepcopy(raw.get(key, {})) for key in STYLE_TOP_LEVEL_KEYS if key in raw}

    brand = result.setdefault("brand", {})
    if not isinstance(brand, dict):
        raise StyleBundleError("style_data.brand must be an object")
    brand["name"] = str(brand.get("name") or "AI Style Template").strip()[:80]
    brand["style_keywords"] = _string_list(brand.get("style_keywords"), "brand.style_keywords", min_items=3, max_items=12)

    canvas = result.setdefault("canvas", {})
    if not isinstance(canvas, dict):
        raise StyleBundleError("style_data.canvas must be an object")
    canvas["aspect_ratio"] = "16:9"
    canvas["width"] = 1920
    canvas["height"] = 1080
    canvas["background"] = _normalize_hex(canvas.get("background") or "#FEFDF9", "canvas.background")
    if canvas["background"] not in NEAR_WHITE_BACKGROUNDS:
        canvas["background"] = "#FEFDF9"
    canvas["subtitle_reserved"] = {"y": 930, "height": 150}

    colors = result.setdefault("colors", {})
    if not isinstance(colors, dict):
        raise StyleBundleError("style_data.colors must be an object")
    background = _normalize_hex(colors.get("background") or canvas["background"], "colors.background")
    if background not in NEAR_WHITE_BACKGROUNDS:
        background = canvas["background"]
    colors["background"] = background
    colors["surface"] = _normalize_hex(colors.get("surface") or "#FFFFFF", "colors.surface")
    colors["paper"] = _normalize_hex(colors.get("paper") or colors["surface"], "colors.paper")
    colors["ink"] = _normalize_hex(colors.get("ink") or "#111111", "colors.ink")
    for optional_key in ("muted_ink", "subtle_ink", "line", "yellow", "yellow_soft", "green_soft", "blue_soft"):
        if optional_key in colors:
            colors[optional_key] = _normalize_hex(colors[optional_key], f"colors.{optional_key}")

    layout = result.setdefault("layout", {})
    if not isinstance(layout, dict):
        raise StyleBundleError("style_data.layout must be an object")
    layout.setdefault("content", {"x": 80, "y": 235, "w": 1760, "h": 680, "frame": "none"})
    layout.setdefault("subtitle_area", {"x": 0, "y": 930, "w": 1920, "h": 150, "fixed": True})

    assets = result.setdefault("visual_assets", {})
    if not isinstance(assets, dict):
        raise StyleBundleError("style_data.visual_assets must be an object")
    unknown_assets = sorted(set(assets) - set(VISUAL_ASSET_ALLOWED_KEYS))
    if unknown_assets:
        raise StyleBundleError(f"visual_assets has unsupported keys: {', '.join(unknown_assets)}")
    assets["image_style"] = str(assets.get("image_style") or "ai_generated_ppt_style").strip()
    assets["diagram_style"] = str(assets.get("diagram_style") or "clean_explainer_diagram").strip()
    assets["required_background"] = "flat_uniform_connected_background"
    layout_rules = _string_list(assets.get("reveal_friendly_layout"), "visual_assets.reveal_friendly_layout", max_items=12)
    required_rules = [
        "四角和四边必须保持连续近白纯色背景，不要纸纹、噪声、阴影、复杂渐变或暗角。",
        "每页 4-8 个独立 visual group，分组之间保留干净背景。",
        "y=930 以下留作视频字幕安全区，不放关键文字、人物或图形。",
    ]
    for rule in required_rules:
        if rule not in layout_rules:
            layout_rules.append(rule)
    assets["reveal_friendly_layout"] = layout_rules
    avoid = _string_list(assets.get("avoid"), "visual_assets.avoid", max_items=20)
    for banned in ("赛博朋克", "复杂 3D 背景", "科技蓝黑风", "AI 生成图里的乱码文字"):
        if banned not in avoid:
            avoid.append(banned)
    assets["avoid"] = avoid

    return result


def normalize_paste_words(value: Any, field_name: str) -> dict[str, Any]:
    """Validate Chinese short text used for template/example reference images."""

    raw = _as_dict(value, field_name)
    title = str(raw.get("title") or "主题标题").strip()[:40]
    subtitle = str(raw.get("subtitle") or "一句话解释核心问题").strip()[:60]
    groups = _string_list(raw.get("groups"), f"{field_name}.groups", min_items=4, max_items=8)
    badges = _string_list(raw.get("badges"), f"{field_name}.badges", max_items=8) if "badges" in raw else []
    return {"title": title, "subtitle": subtitle, "groups": groups, "badges": badges}


def validate_style_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized, safe style bundle or raise StyleBundleError."""

    raw = _as_dict(bundle, "bundle")
    required = {
        "name",
        "description",
        "style_data",
        "template_paste_words",
        "example_paste_words",
        "template_image_prompt",
        "example_image_prompt",
        "negative_prompt",
    }
    missing = sorted(key for key in required if key not in raw)
    if missing:
        raise StyleBundleError(f"bundle is missing required keys: {', '.join(missing)}")

    normalized = {
        "name": str(raw.get("name") or "AI 图片风格模板").strip()[:60],
        "description": str(raw.get("description") or "").strip()[:500],
        "style_data": normalize_style_data(raw["style_data"]),
        "template_paste_words": normalize_paste_words(raw["template_paste_words"], "template_paste_words"),
        "example_paste_words": normalize_paste_words(raw["example_paste_words"], "example_paste_words"),
        "template_image_prompt": str(raw.get("template_image_prompt") or "").strip(),
        "example_image_prompt": str(raw.get("example_image_prompt") or "").strip(),
        "negative_prompt": str(raw.get("negative_prompt") or "").strip(),
    }
    if not normalized["template_image_prompt"]:
        raise StyleBundleError("template_image_prompt cannot be empty")
    if not normalized["example_image_prompt"]:
        raise StyleBundleError("example_image_prompt cannot be empty")
    return normalized


def style_bundle_to_yaml(bundle: dict[str, Any]) -> str:
    """Serialize a validated bundle's style_data into editable YAML."""

    normalized = validate_style_bundle(bundle)
    return yaml.safe_dump(
        normalized["style_data"],
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    ).strip()


def bundle_prompt_preview(bundle: dict[str, Any]) -> str:
    """Human-readable preview for UI display and debugging."""

    normalized = validate_style_bundle(bundle)
    return json.dumps(
        {
            "name": normalized["name"],
            "template_paste_words": normalized["template_paste_words"],
            "example_paste_words": normalized["example_paste_words"],
            "template_image_prompt": normalized["template_image_prompt"],
            "example_image_prompt": normalized["example_image_prompt"],
            "negative_prompt": normalized["negative_prompt"],
        },
        ensure_ascii=False,
        indent=2,
    )
