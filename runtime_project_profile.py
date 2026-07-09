"""Project Profile v1 runtime bridge.

Exposes the AI image-style generation API without rewriting the existing large
server.py. Project-profile templates and get/put routes are owned by
runtime_project_profile_templates_override.py and
runtime_project_profile_lightweight.py respectively.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_project_profile_runtime_patch__"
AI_IMAGE_STYLE_SOURCE = "ai_text_generated"


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
    parts.extend([
        "Production invariants:",
        "- Generated slide images must use a flat pure-white #FFFFFF outer canvas.",
        "- Keep visual elements separated; no touching, sticking, overlapping, or dense collage.",
        "- Reserve lower subtitle-safe area where the project requires subtitles.",
        "- Final video background is handled separately and must not appear in visual_draft.png.",
        "Negative rules:",
    ])
    for rule in style.get("negative_prompt_rules") or []:
        parts.append(f"- {rule}")
    return "\n".join(part for part in parts if str(part).strip())


def normalize_generated_image_style(value: Any, requirement: str = "") -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    style = {
        "source": AI_IMAGE_STYLE_SOURCE,
        "template_id": "ai_generated",
        "template_name": _safe_text(source.get("style_name") or "AI 生成图片风格", 80),
        "style_name": _safe_text(source.get("style_name") or "AI 生成图片风格", 80),
        "style_summary": _safe_text(source.get("style_summary") or source.get("summary") or requirement, 1000),
        "custom_requirement": _safe_text(requirement or source.get("custom_requirement"), 4000),
        "visual_language": _safe_dict(source.get("visual_language")),
        "maskability_rules": _merge_required_rules(_safe_list(source.get("maskability_rules"), 16)),
        "negative_prompt_rules": _safe_list(source.get("negative_prompt_rules"), 16),
        "sample_reference_image_prompts": _safe_list(source.get("sample_reference_image_prompts"), 3),
        "reference_image_count_target": _safe_int(source.get("reference_image_count_target"), 3, 0, 3),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    style["system_content"] = _safe_text(source.get("system_content") or _build_system_content(style), 12000)
    return style


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
    system_prompt = """
你是 PPT 视频系统的图片风格设计专家。
你的任务是根据用户的文字需求，生成一套可复用的图片风格配置，用于批量生成 16:9 slide visual_draft.png。
必须遵守生产不变量：visual_draft.png 外背景永远是纯白 #FFFFFF；最终视频背景单独合成；元素之间必须分离、不能粘连、不能重叠，方便后续 AI Mask 和手动 Mask reveal。
只输出 JSON，不要输出解释文字。
""".strip()
    output_schema = {
        "style_name": "中文风格名称",
        "style_summary": "一句话说明适合的内容、受众和观感",
        "system_content": "给生图模型使用的英文风格 system content，必须包含 pure-white outer canvas、separated elements、no overlapping、no texture background 等生产约束",
        "visual_language": {
            "line_style": "线条风格",
            "shape_language": "形状语言",
            "color_palette": ["#FFFFFF", "#..."],
            "texture": "纹理/材质要求",
            "layout_density": "布局密度",
            "typography": "标题和短标签风格",
            "composition": "构图规则",
        },
        "maskability_rules": ["方便 Mask reveal 的正向规则"],
        "negative_prompt_rules": ["必须避免的内容"],
        "sample_reference_image_prompts": ["可用于生成风格参考图的英文 prompt，最多 3 条"],
    }
    user_prompt = json.dumps(
        {
            "user_requirement": requirement,
            "project_context": project_context,
            "base_template": base_template,
            "fixed_output_schema": output_schema,
        },
        ensure_ascii=False,
        indent=2,
    )
    try:
        client = server_module.get_openai_client(api_key=api_key, base_url=base_url, timeout=90.0, max_retries=1)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.35,
            max_tokens=2500,
            timeout=90,
        )
        raw_content = str(response.choices[0].message.content or "").strip()
        parsed = json.loads(_clean_json_markdown(raw_content))
        return normalize_generated_image_style(parsed, requirement)
    except json.JSONDecodeError as exc:
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


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app") and hasattr(module, "Project")]


def _install_when_ready() -> None:
    def worker() -> None:
        while not os.environ.get("PPT_STUDIO_DISABLE_PROJECT_PROFILE"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(target=worker, name="ppt-project-profile-runtime", daemon=True).start()


_install_when_ready()
