"""Utilities for producing and validating AI-generated image style template bundles.

This module intentionally contains no FastAPI or database code. The server can call
these helpers to preview an AI style package, then later materialize it as a reusable
image-style template.

Style bundles are allowed to generalize visual language, but they must not override
production invariants such as generated-image size, pure-white source background,
subtitle safety zone, title requirement, or maskability.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any

import yaml


STYLE_TOP_LEVEL_KEYS = ("brand", "canvas", "colors", "layout", "visual_assets")
LANDSCAPE_CANVAS = {
    "orientation": "landscape",
    "aspect_ratio": "16:9",
    "width": 1920,
    "height": 1080,
    "subtitle_safe_zone": {"top": 930, "bottom": 1080},
    "content_safe_area": {"left": 80, "top": 235, "right": 1840, "bottom": 930},
}


def _resolve_canvas(canvas_profile: Any = None) -> dict[str, Any]:
    """Resolve a canvas profile dict; unknown shapes fall back to landscape."""
    if not isinstance(canvas_profile, dict):
        return copy.deepcopy(LANDSCAPE_CANVAS)
    width = int(canvas_profile.get("width") or 0)
    height = int(canvas_profile.get("height") or 0)
    if width <= 0 or height <= 0:
        return copy.deepcopy(LANDSCAPE_CANVAS)
    subtitle = canvas_profile.get("subtitle_safe_zone")
    subtitle = subtitle if isinstance(subtitle, dict) else {}
    content = canvas_profile.get("content_safe_area")
    content = content if isinstance(content, dict) else {}
    return {
        "orientation": str(canvas_profile.get("orientation") or ("portrait" if height > width else "landscape")),
        "aspect_ratio": str(canvas_profile.get("aspect_ratio") or "16:9"),
        "width": width,
        "height": height,
        "subtitle_safe_zone": {
            "top": int(subtitle.get("top") or round(height * 0.861)),
            "bottom": int(subtitle.get("bottom") or height),
        },
        "content_safe_area": {
            "left": int(content.get("left") or 80),
            "top": int(content.get("top") or 235),
            "right": int(content.get("right") or (width - 80)),
            "bottom": int(content.get("bottom") or int(subtitle.get("top") or round(height * 0.861))),
        },
    }


VISUAL_ASSET_ALLOWED_KEYS = (
    "image_style",
    "diagram_style",
    "required_background",
    "reveal_friendly_layout",
    "avoid",
)
HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
GENERATED_IMAGE_BACKGROUND = "#FFFFFF"
FINAL_CANVAS_NEAR_WHITE_BACKGROUNDS = {"#FFFFFF", "#FFFDF7", "#FEFDF9"}
FIXED_SUBTITLE_AREA = {"x": 0, "y": 930, "w": 1920, "h": 150, "fixed": True}


def _fixed_subtitle_area(canvas: dict[str, Any] | None = None) -> dict[str, Any]:
    if not canvas:
        return dict(FIXED_SUBTITLE_AREA)
    zone = canvas.get("subtitle_safe_zone") or {}
    return {
        "x": 0,
        "y": int(zone.get("top") or 930),
        "w": int(canvas.get("width") or 1920),
        "h": int(canvas.get("height") or 1080) - int(zone.get("top") or 930),
        "fixed": True,
    }


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


def style_bundle_system_prompt(canvas_profile: Any = None) -> str:
    """Return the system prompt for asking an LLM to draft a style bundle."""

    canvas = _resolve_canvas(canvas_profile)
    zone = canvas["subtitle_safe_zone"]
    invariant_text = (
        f"{canvas['width']}x{canvas['height']}、{canvas['aspect_ratio']}"
        f"、纯白 #FFFFFF 外围画布、y={zone['top']}..{zone['bottom']} 视频字幕安全区"
    )
    return (
        "<PromptVersion>style_bundle_v2_minimal</PromptVersion>\n\n"
        "## 目的\n把用户需求转成可复用的图片风格模板包，只决定视觉语言，不设计具体页面内容。\n\n"
        "## 输入\nUser Content 是 JSON，只包含用户实际提供的 requirement、name、audience、sample_topic 和可选 base_style；缺失字段不得擅自补成特殊领域偏好。\n\n"
        f"## 系统背景\n程序会确定性补齐 {invariant_text}、唯一主标题和 Mask 可分离规则。style_data 只描述字体气质、线条、图标、图表、强调色、卡片形状和构图偏好，不重复生产铁律，不生成页面副标题。\n\n"
        "## 输出\n只输出合法 JSON 对象，不要 Markdown、解释或前后缀文本。根字段必须且只能是 name、description、style_data、template_paste_words、example_paste_words、template_image_prompt、example_image_prompt、negative_prompt；style_data 只能包含 brand、canvas、colors、layout、visual_assets。template_paste_words 和 example_paste_words 只包含 title、groups 和可选 badges。\n\n"
        "## 规则\n只能泛化风格，不复制品牌、角色、文字内容或具体构图。所有贴词使用简短中文；视觉组数量由示例内容自然决定，不为凑数量强拆卡片。禁止深色整页背景、纸纹、噪声、暗角、复杂 3D、赛博朋克和科技蓝黑大背景。"
    )


def build_style_bundle_user_prompt(request: dict[str, Any], base_style_text: str = "") -> str:
    """Build a deterministic user prompt for the style-bundle LLM call."""

    name = str(request.get("name") or "").strip()
    brief = str(request.get("brief") or "").strip()
    audience = str(request.get("audience") or "").strip()
    sample_topic = str(request.get("sample_topic") or "").strip()
    base = base_style_text.strip()
    payload: dict[str, Any] = {"requirement": brief}
    for key, value in (("name", name), ("audience", audience), ("sample_topic", sample_topic)):
        if value:
            payload[key] = value
    if base:
        payload["base_style"] = base
    return json.dumps(payload, ensure_ascii=False)


def normalize_style_data(style_data: dict[str, Any], canvas_profile: Any = None) -> dict[str, Any]:
    """Validate and normalize the style_data section returned by the LLM."""

    canvas_profile_resolved = _resolve_canvas(canvas_profile)
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
    canvas["aspect_ratio"] = canvas_profile_resolved["aspect_ratio"]
    canvas["width"] = canvas_profile_resolved["width"]
    canvas["height"] = canvas_profile_resolved["height"]
    canvas["background"] = GENERATED_IMAGE_BACKGROUND
    canvas["generated_image_background"] = GENERATED_IMAGE_BACKGROUND
    subtitle_zone = canvas_profile_resolved["subtitle_safe_zone"]
    canvas["subtitle_reserved"] = {
        "y": subtitle_zone["top"],
        "height": subtitle_zone["bottom"] - subtitle_zone["top"],
    }

    colors = result.setdefault("colors", {})
    if not isinstance(colors, dict):
        raise StyleBundleError("style_data.colors must be an object")
    background = _normalize_hex(colors.get("background") or GENERATED_IMAGE_BACKGROUND, "colors.background")
    if background not in FINAL_CANVAS_NEAR_WHITE_BACKGROUNDS:
        background = GENERATED_IMAGE_BACKGROUND
    colors["background"] = background
    colors["generated_image_background"] = GENERATED_IMAGE_BACKGROUND
    colors["surface"] = _normalize_hex(colors.get("surface") or "#FFFFFF", "colors.surface")
    colors["paper"] = _normalize_hex(colors.get("paper") or colors["surface"], "colors.paper")
    colors["ink"] = _normalize_hex(colors.get("ink") or "#111111", "colors.ink")
    for optional_key in ("muted_ink", "subtle_ink", "line", "yellow", "yellow_soft", "green_soft", "blue_soft"):
        if optional_key in colors:
            colors[optional_key] = _normalize_hex(colors[optional_key], f"colors.{optional_key}")

    layout = result.setdefault("layout", {})
    if not isinstance(layout, dict):
        raise StyleBundleError("style_data.layout must be an object")
    content_area = canvas_profile_resolved["content_safe_area"]
    layout.setdefault(
        "content",
        {
            "x": content_area["left"],
            "y": content_area["top"],
            "w": content_area["right"] - content_area["left"],
            "h": content_area["bottom"] - content_area["top"],
            "frame": "none",
        },
    )
    layout["subtitle_area"] = _fixed_subtitle_area(canvas_profile_resolved)

    assets = result.setdefault("visual_assets", {})
    if not isinstance(assets, dict):
        raise StyleBundleError("style_data.visual_assets must be an object")
    unknown_assets = sorted(set(assets) - set(VISUAL_ASSET_ALLOWED_KEYS))
    if unknown_assets:
        raise StyleBundleError(f"visual_assets has unsupported keys: {', '.join(unknown_assets)}")
    assets["image_style"] = str(assets.get("image_style") or "ai_generated_ppt_style").strip()
    assets["diagram_style"] = str(assets.get("diagram_style") or "clean_explainer_diagram").strip()
    assets["required_background"] = "flat_uniform_pure_white_generated_image"
    layout_rules = _string_list(assets.get("reveal_friendly_layout"), "visual_assets.reveal_friendly_layout", max_items=12)
    required_rules = [
        "生成图片背景固定为 #FFFFFF；四角和四边必须保持连续纯白，不要纸纹、噪声、阴影、复杂渐变或暗角。",
        f"y={subtitle_zone['top']} 以下是视频字幕安全区，不放任何文字、人物、图标、箭头、装饰、阴影或残片。",
        "视觉组数量由内容自然决定；一个完整正文视觉组也是合法结果，不要为了 Mask 强行拆成大量孤立卡片。",
        "语义组必须可人工 Mask；允许清晰箭头、括号、路径或流程线连接，但禁止箭头穿字、严重遮挡和无关组粘连。",
    ]
    for rule in required_rules:
        if rule not in layout_rules:
            layout_rules.append(rule)
    assets["reveal_friendly_layout"] = layout_rules
    avoid = _string_list(assets.get("avoid"), "visual_assets.avoid", max_items=20)
    for banned in ("整页深色背景", "纸纹背景", "背景噪声", "赛博朋克", "复杂 3D 背景", "科技蓝黑风", "AI 生成图里的乱码文字", "严重遮挡", "箭头穿字"):
        if banned not in avoid:
            avoid.append(banned)
    assets["avoid"] = avoid

    return result


def normalize_paste_words(value: Any, field_name: str) -> dict[str, Any]:
    """Validate Chinese short text used for template/example reference images."""

    raw = _as_dict(value, field_name)
    title = str(raw.get("title") or "主题标题").strip()[:40]
    groups = _string_list(raw.get("groups"), f"{field_name}.groups", min_items=1, max_items=12)
    badges = _string_list(raw.get("badges"), f"{field_name}.badges", max_items=8) if "badges" in raw else []
    return {"title": title, "groups": groups, "badges": badges}


def validate_style_bundle(bundle: dict[str, Any], canvas_profile: Any = None) -> dict[str, Any]:
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
        "style_data": normalize_style_data(raw["style_data"], canvas_profile),
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


def style_bundle_to_yaml(bundle: dict[str, Any], canvas_profile: Any = None) -> str:
    """Serialize a validated bundle's style_data into editable YAML."""

    normalized = validate_style_bundle(bundle, canvas_profile)
    return yaml.safe_dump(
        normalized["style_data"],
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    ).strip()


def bundle_prompt_preview(bundle: dict[str, Any], canvas_profile: Any = None) -> str:
    """Human-readable preview for UI display and debugging."""

    normalized = validate_style_bundle(bundle, canvas_profile)
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
