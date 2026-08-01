"""Step 2 Prompt files, reusable templates, migration, and composed previews."""

from __future__ import annotations

from datetime import datetime
import hashlib
import logging
import os
import re
from typing import Any, Callable, Dict, List
import uuid

from fastapi import HTTPException

from database import Project
from pipeline_lifecycle import write_json_atomic
from repository_paths import STEP2_PROMPT_TEMPLATE_FILES, STEP2_PROMPT_TEMPLATES_PATH
from runtime_support import read_json_file as _default_read_json_file


logger = logging.getLogger("PPTStudio.StoryboardPrompts")

STEP2_PROMPTS_FILE = "step2_prompts.json"
STEP2_SCRIPT_PLAN_FILE = "slide_script_plan.json"
STEP2_VISUAL_PLAN_FILE = "slide_visual_plan.json"


def _default_normalized_template_name(value: Any) -> str:
    name = re.sub(r"\s+", " ", str(value or "").strip())
    if not name:
        raise HTTPException(status_code=400, detail="模板名称不能为空")
    if len(name) > 60:
        raise HTTPException(status_code=400, detail="模板名称不能超过 60 个字符")
    return name


def _default_template_timestamp() -> str:
    return datetime.now().isoformat(timespec="seconds")


read_json_file: Callable[..., Any] = _default_read_json_file
normalized_template_name: Callable[..., str] = _default_normalized_template_name
template_timestamp: Callable[[], str] = _default_template_timestamp
AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION = ""
LEGACY_STEP2_PROMPT_HASHES: dict[str, set[str]] = {}
LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH = ""


def configure_storyboard_prompt_templates(
    *,
    read_json: Callable[..., Any],
    normalize_template_name: Callable[..., str],
    timestamp: Callable[[], str],
    ai_knowledge_script_extension: str,
    legacy_prompt_hashes: dict[str, set[str]],
    legacy_interview_script_prompt_hash: str,
) -> None:
    global read_json_file
    global normalized_template_name
    global template_timestamp
    global AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION
    global LEGACY_STEP2_PROMPT_HASHES
    global LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH
    read_json_file = read_json
    normalized_template_name = normalize_template_name
    template_timestamp = timestamp
    AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION = ai_knowledge_script_extension
    LEGACY_STEP2_PROMPT_HASHES = legacy_prompt_hashes
    LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH = legacy_interview_script_prompt_hash


def step2_prompts_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", STEP2_PROMPTS_FILE)


def step2_script_plan_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", STEP2_SCRIPT_PLAN_FILE)


def step2_visual_plan_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", STEP2_VISUAL_PLAN_FILE)


def read_prompt_template(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read().strip()


def default_step2_prompts() -> Dict[str, str]:
    return {
        key: read_prompt_template(path)
        for key, path in STEP2_PROMPT_TEMPLATE_FILES.items()
    }


def normalized_prompt_hash(value: Any) -> str:
    text = str(value or "").replace("\r\n", "\n").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def migrate_legacy_step2_prompt(key: str, value: str, defaults: Dict[str, str]) -> str:
    """Upgrade untouched built-in prompts while preserving genuinely customized text."""
    prompt_hash = normalized_prompt_hash(value)
    if prompt_hash in LEGACY_STEP2_PROMPT_HASHES.get(key, set()):
        return defaults[key]
    if key == "script_system" and prompt_hash == LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH:
        return value.replace(
            "<ContractVersion>step2_script_v4_no_subtitle</ContractVersion>",
            "<ContractVersion>step2_script_v5_speech_driven_interview</ContractVersion>",
            1,
        )
    return value


def read_step2_prompts(project: Project) -> Dict[str, str]:
    prompts = default_step2_prompts()
    defaults = dict(prompts)
    stored = read_json_file(step2_prompts_path(project), {})
    if isinstance(stored, dict):
        for key in prompts:
            value = str(stored.get(key) or "").strip()
            if value:
                prompts[key] = migrate_legacy_step2_prompt(key, value, defaults)
    return prompts


def normalize_step2_prompt_type(value: Any) -> str:
    prompt_type = str(value or "script").strip().lower()
    if prompt_type not in {"script", "visual"}:
        raise HTTPException(status_code=400, detail="Prompt 模板类型必须是 script 或 visual")
    return prompt_type


def step2_prompt_keys(prompt_type: str) -> tuple[str, str]:
    return ("visual_system", "visual_output_example") if prompt_type == "visual" else ("script_system", "script_output_example")


def step2_prompt_template_payload(
    template_id: str,
    name: str,
    prompt_type: str,
    prompts: Dict[str, str],
    built_in: bool = False,
    updated_at: str = "",
) -> Dict[str, Any]:
    first_key, second_key = step2_prompt_keys(prompt_type)
    return {
        "id": template_id,
        "name": name,
        "prompt_type": prompt_type,
        "built_in": built_in,
        "updated_at": updated_at,
        "prompts": {
            first_key: str(prompts.get(first_key) or ""),
            second_key: str(prompts.get(second_key) or ""),
        },
    }


def built_in_step2_prompt_templates() -> List[Dict[str, Any]]:
    defaults = default_step2_prompts()
    ai_knowledge_prompts = dict(defaults)
    ai_knowledge_prompts["script_system"] = (
        defaults["script_system"] + "\n\n" + AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION
    )
    return [
        step2_prompt_template_payload(
            "builtin_article_to_slide",
            "原始模板 · 文章→slides",
            "script",
            defaults,
            built_in=True,
        ),
        step2_prompt_template_payload(
            "builtin_ai_knowledge_to_slide",
            "AI 知识科普 · 文章→slides",
            "script",
            ai_knowledge_prompts,
            built_in=True,
        ),
        step2_prompt_template_payload(
            "builtin_slide_to_visualization",
            "原始模板 · slides→可视化",
            "visual",
            defaults,
            built_in=True,
        ),
    ]


def list_step2_prompt_templates() -> List[Dict[str, Any]]:
    templates = built_in_step2_prompt_templates()
    stored = read_json_file(STEP2_PROMPT_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        return templates
    for item in stored:
        if not isinstance(item, dict):
            continue
        try:
            prompt_type = normalize_step2_prompt_type(item.get("prompt_type"))
            templates.append(
                step2_prompt_template_payload(
                    str(item.get("id") or ""),
                    str(item.get("name") or ""),
                    prompt_type,
                    item.get("prompts") if isinstance(item.get("prompts"), dict) else item,
                    updated_at=str(item.get("updated_at") or ""),
                )
            )
        except HTTPException as exc:
            logger.warning("Skipping invalid Step 2 prompt template %s: %s", item.get("id"), exc.detail)
    return templates


def step2_prompt_template_detail(template_id: str) -> Dict[str, Any]:
    for template in list_step2_prompt_templates():
        if template["id"] == template_id:
            return template
    raise HTTPException(status_code=404, detail="Prompt 模板不存在")


def get_step2_prompt_templates():
    return {"success": True, "templates": list_step2_prompt_templates()}


def get_step2_prompt_template(template_id: str):
    return {"success": True, "template": step2_prompt_template_detail(template_id)}


def save_step2_prompt_template(payload: Dict[str, Any]):
    name = normalized_template_name(payload.get("name"))
    prompt_type = normalize_step2_prompt_type(payload.get("prompt_type"))
    protected_names = {template["name"].casefold() for template in built_in_step2_prompt_templates()}
    if name.casefold() in protected_names:
        raise HTTPException(status_code=400, detail="内置 Prompt 模板名称不可覆盖")

    first_key, second_key = step2_prompt_keys(prompt_type)
    prompts = {
        first_key: str(payload.get(first_key) or "").strip(),
        second_key: str(payload.get(second_key) or "").strip(),
    }
    if not prompts[first_key] or not prompts[second_key]:
        raise HTTPException(status_code=400, detail="Prompt 模板内容不能为空")

    stored = read_json_file(STEP2_PROMPT_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        stored = []
    existing = next(
        (
            item
            for item in stored
            if isinstance(item, dict)
            and str(item.get("prompt_type") or "").strip().lower() == prompt_type
            and str(item.get("name") or "").strip().casefold() == name.casefold()
        ),
        None,
    )
    now = template_timestamp()
    if existing is None:
        existing = {"id": uuid.uuid4().hex[:12], "created_at": now}
        stored.append(existing)
    existing.update(
        {
            "name": name,
            "prompt_type": prompt_type,
            "prompts": prompts,
            "updated_at": now,
        }
    )
    write_json_atomic(STEP2_PROMPT_TEMPLATES_PATH, stored)
    return {
        "success": True,
        "template": step2_prompt_template_payload(str(existing["id"]), name, prompt_type, prompts, updated_at=now),
        "templates": list_step2_prompt_templates(),
    }


def delete_step2_prompt_template(template_id: str):
    if any(template["id"] == template_id for template in built_in_step2_prompt_templates()):
        raise HTTPException(status_code=400, detail="内置 Prompt 模板不能删除")
    if not re.fullmatch(r"[0-9a-f]{12}", template_id):
        raise HTTPException(status_code=404, detail="Prompt 模板不存在")
    stored = read_json_file(STEP2_PROMPT_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        stored = []
    next_stored = [
        item
        for item in stored
        if not (isinstance(item, dict) and str(item.get("id") or "") == template_id)
    ]
    if len(next_stored) == len(stored):
        raise HTTPException(status_code=404, detail="Prompt 模板不存在")
    write_json_atomic(STEP2_PROMPT_TEMPLATES_PATH, next_stored)
    return {"success": True, "templates": list_step2_prompt_templates()}


def compose_step2_system_prompt(system_content: str, output_example: str) -> str:
    return (
        str(system_content or "").strip()
        + "\n\n<OutputExample>\n"
        + str(output_example or "").strip()
        + "\n</OutputExample>"
    )


def step2_script_prompt_uses_legacy_contract(system_content: str) -> bool:
    """Detect old prompts that require fields removed from the Step 2A input/output contract."""
    text = str(system_content or "")
    if "step2_script_v5_speech_driven" in text or "step2_script_v4_no_subtitle" in text:
        return False
    if "step2_script_v2" in text or "step2_script_v3_narration_first" in text:
        return True
    legacy_patterns = (
        r"body_points\s*(?:必须|應|应|需|是)",
        r"narration_segments\s*(?:必须|應|应|需|是)",
        r"讲解分段要求",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in legacy_patterns)


def step2_visual_prompt_uses_legacy_contract(system_content: str) -> bool:
    """Detect prompts that depend on Step 2A fields no longer sent to Step 2B."""
    text = str(system_content or "")
    if "step2_visual_v6_atomic" in text or "step2_visual_v5_no_subtitle" in text:
        return False
    if "step2_visual_v2" in text or "step2_visual_v4_one_to_one" in text:
        return True
    legacy_patterns = (
        r"narration_segments\[\].{0,40}(?:唯一依据|唯一依據)",
        r"第\s*i\s*个\s*body_point",
        r"body_points\[i-1\]",
        r"seg_\(i\+1\)",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL) for pattern in legacy_patterns)


def step2_prompt_compatibility(prompts: Dict[str, str]) -> Dict[str, Any]:
    script_legacy = step2_script_prompt_uses_legacy_contract(prompts.get("script_system", ""))
    visual_legacy = step2_visual_prompt_uses_legacy_contract(prompts.get("visual_system", ""))
    return {
        "contract_version": "step2_narration_visual_v5_speech_atomic",
        "script_prompt_legacy": script_legacy,
        "visual_prompt_legacy": visual_legacy,
        "compatible": not script_legacy and not visual_legacy,
    }


def step2_prompt_response(project: Project) -> Dict[str, Any]:
    prompts = read_step2_prompts(project)
    return {
        "success": True,
        "prompts": prompts,
        "defaults": default_step2_prompts(),
        "compatibility": step2_prompt_compatibility(prompts),
        "composed": {
            "script_system_content": compose_step2_system_prompt(
                prompts["script_system"],
                prompts["script_output_example"],
            ),
            "visual_system_content": compose_step2_system_prompt(
                prompts["visual_system"],
                prompts["visual_output_example"],
            ),
        },
    }


