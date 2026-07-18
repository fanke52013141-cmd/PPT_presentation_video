"""Project Profile v1 runtime bridge.

Exposes the AI image-style generation API without rewriting the existing large
server.py. Project-profile templates and get/put routes are owned by
runtime_project_profile_templates_override.py and
runtime_project_profile_lightweight.py respectively.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_project_profile_runtime_patch__"
AI_IMAGE_STYLE_SOURCE = "ai_text_generated"
AI_IMAGE_STYLE_SYSTEM_PROMPT = """<PromptVersion>image_style_text_generation_v2_minimal</PromptVersion>

You design reusable visual-language profiles for a PPT video image pipeline.

The user provides one required `requirement` and may provide `project_context` or a compact `base_style` to adapt. Decide only the reusable look: line, shape, palette, texture, lighting, density, typography, composition, iconography, style-specific negatives, and up to three short content-neutral reference-image scene briefs.

Production code deterministically adds the 1920x1080 canvas, pure-white outer background, subtitle-safe area, separated Mask boundaries, and final-video-background rules. Do not repeat those universal rules and do not output `system_content` or `maskability_rules`.

Return one valid JSON object with exactly: `style_name`, `style_summary`, `visual_language`, `negative_prompt_rules`, `sample_reference_image_prompts`. Do not output Markdown or explanations."""


def _safe_text(value: Any, limit: int = 12000) -> str:
    text = str(value or "").strip()
    return text[:limit]


def _safe_int(value: Any, default: int = 0, minimum: int = 0, maximum: int = 3) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _safe_list(value: Any, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _safe_text(item, 500)
        if text:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _safe_dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key, item in value.items():
        key_text = _safe_text(key, 80)
        if not key_text:
            continue
        if isinstance(item, list):
            result[key_text] = _safe_list(item, 12)
        elif isinstance(item, dict):
            result[key_text] = {str(k)[:80]: _safe_text(v, 500) for k, v in item.items()}
        else:
            result[key_text] = _safe_text(item, 1000)
    return result


def _merge_required_rules(rules: list[str]) -> list[str]:
    merged = list(rules)
    required = [
        "Generated slide images must use a flat pure-white #FFFFFF outer background.",
        "Keep all semantic visual groups separated by clear white gaps for Mask reveal.",
        "Do not bake final-video background color or image into visual_draft.png.",
    ]
    for rule in required:
        if rule not in merged:
            merged.append(rule)
    return merged


def _build_system_content(style: dict[str, Any]) -> str:
    visual = style.get("visual_language") if isinstance(style.get("visual_language"), dict) else {}
    parts = [
        f"Image style name: {style.get('style_name') or 'AI-generated reusable style'}.",
        f"Style summary: {style.get('style_summary') or ''}",
        "Visual language:",
    ]
    for key, value in visual.items():
        parts.append(f"- {key}: {value}")
    negative_rules = style.get("negative_prompt_rules") or []
    if negative_rules:
        parts.append("Style-specific negative rules:")
        for rule in negative_rules:
            parts.append(f"- {rule}")
    return "\n".join(part for part in parts if str(part).strip())


def _compact_base_style(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    compact: dict[str, Any] = {
        "style_name": _safe_text(source.get("style_name"), 120),
        "style_summary": _safe_text(source.get("style_summary"), 1000),
        "visual_language": _safe_dict(source.get("visual_language")),
        "negative_prompt_rules": _safe_list(source.get("negative_prompt_rules"), 16),
    }
    compact = {key: item for key, item in compact.items() if item not in (None, "", [], {})}
    return compact


def build_text_image_style_user_prompt(
    requirement: str,
    project_context: str = "",
    base_template: Any = None,
) -> str:
    payload: dict[str, Any] = {"requirement": _safe_text(requirement, 4000)}
    context = _safe_text(project_context, 2000)
    base_style = _compact_base_style(base_template)
    if context:
        payload["project_context"] = context
    if base_style:
        payload["base_style"] = base_style
    return json.dumps(payload, ensure_ascii=False)


def normalize_generated_image_style(value: Any, requirement: str = "") -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    sample_prompts = _safe_list(source.get("sample_reference_image_prompts"), 3)
    style = {
        "source": AI_IMAGE_STYLE_SOURCE,
        "template_id": "ai_generated",
        "template_name": _safe_text(source.get("style_name") or "AI 生成图片风格", 80),
        "style_name": _safe_text(source.get("style_name") or "AI 生成图片风格", 80),
        "style_summary": _safe_text(source.get("style_summary") or source.get("summary") or requirement, 1000),
        "custom_requirement": _safe_text(requirement or source.get("custom_requirement"), 4000),
        "visual_language": _safe_dict(source.get("visual_language")),
        # Universal production rules are owned by code.  Never trust hidden
        # fields that the model was explicitly told not to return.
        "maskability_rules": _merge_required_rules([]),
        "negative_prompt_rules": _safe_list(source.get("negative_prompt_rules"), 16),
        "sample_reference_image_prompts": sample_prompts,
        "reference_image_count_target": 3,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    style["system_content"] = _safe_text(_build_system_content(style), 12000)
    return style


def validate_generated_image_style_model_output(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("图片风格输出必须是 JSON 对象")
    expected = {
        "style_name",
        "style_summary",
        "visual_language",
        "negative_prompt_rules",
        "sample_reference_image_prompts",
    }
    unexpected = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if missing:
        raise ValueError(f"图片风格输出缺少字段: {', '.join(missing)}")
    if unexpected:
        raise ValueError(f"图片风格输出包含未声明字段: {', '.join(unexpected)}")
    if not _safe_text(value.get("style_name"), 120) or not _safe_text(value.get("style_summary"), 1000):
        raise ValueError("style_name 和 style_summary 不能为空")
    if not isinstance(value.get("visual_language"), dict) or not value.get("visual_language"):
        raise ValueError("visual_language 必须是非空对象")
    for key in ("negative_prompt_rules", "sample_reference_image_prompts"):
        if not isinstance(value.get(key), list):
            raise ValueError(f"{key} 必须是数组")
    return value


def _clean_json_markdown(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.I).strip()
        value = re.sub(r"\s*```$", "", value, flags=re.I).strip()
    start = value.find("{")
    end = value.rfind("}")
    if start >= 0 and end > start:
        return value[start : end + 1]
    return value


def _generate_image_style_with_llm(server_module: ModuleType, payload: dict[str, Any]) -> dict[str, Any]:
    requirement = _safe_text(payload.get("requirement") or payload.get("custom_requirement"), 4000)
    if not requirement:
        raise server_module.HTTPException(status_code=400, detail="请先输入图片风格需求")

    get_setting = getattr(server_module, "get_setting", None)
    if not callable(get_setting):
        raise server_module.HTTPException(status_code=500, detail="当前服务无法读取 LLM 设置")
    api_key = _safe_text(get_setting("llm_api_key"), 4000)
    model = _safe_text(get_setting("llm_model"), 200)
    base_url = _safe_text(get_setting("llm_base_url"), 1000) or None
    if not api_key or not model:
        raise server_module.HTTPException(status_code=400, detail="请先在系统设置中配置文本模型 API Key 和模型名称")

    base_template = payload.get("base_template") if isinstance(payload.get("base_template"), dict) else {}
    project_context = _safe_text(payload.get("project_context"), 2000)
    user_prompt = build_text_image_style_user_prompt(requirement, project_context, base_template)
    try:
        client = server_module.get_openai_client(api_key=api_key, base_url=base_url, timeout=90.0, max_retries=1)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": AI_IMAGE_STYLE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.35,
            max_tokens=2500,
            timeout=90,
        )
        raw_content = str(response.choices[0].message.content or "").strip()
        parsed = json.loads(_clean_json_markdown(raw_content))
        validate_generated_image_style_model_output(parsed)
        return normalize_generated_image_style(parsed, requirement)
    except (json.JSONDecodeError, ValueError) as exc:
        raise server_module.HTTPException(status_code=500, detail=f"AI 返回的图片风格 JSON 解析失败: {exc}") from exc
    except server_module.HTTPException:
        raise
    except Exception as exc:
        raise server_module.HTTPException(status_code=500, detail=f"AI 生成图片风格失败: {exc}") from exc


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db")
    if not all(hasattr(server_module, name) for name in required):
        return False
    app = server_module.app

    def generate_image_style(payload: dict[str, Any]) -> dict[str, Any]:
        style = _generate_image_style_with_llm(server_module, payload if isinstance(payload, dict) else {})
        return {"success": True, "style": style}

    app.add_api_route("/api/project-profile/image-style/generate", generate_image_style, methods=["POST"])
    setattr(server_module, PATCH_MARKER, True)
    return True
