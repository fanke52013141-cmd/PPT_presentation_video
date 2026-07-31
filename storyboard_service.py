"""Step 2 storyboard planning, templates, and contract lifecycle."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional
import uuid

from fastapi import Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
import yaml

from config_store import get_setting
from database import Project, get_db
import invalidation_service
from pipeline_lifecycle import write_json_atomic
from project_storage import slide_file as storage_slide_file
from scripts.pipeline_profiles import (
    read_pipeline_profile,
    role_catalog,
    storyboard_profile_prompt,
    storyboard_requirements,
)
from visual_contract_service import normalize_visual_type


logger = logging.getLogger("PPTStudio.Storyboard")

REPO_ROOT = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(REPO_ROOT, "data")
STORYBOARD_TEMPLATES_PATH = os.path.join(
    DATA_DIR,
    "storyboard_templates.json",
)
STEP2_PROMPT_TEMPLATES_PATH = os.path.join(
    DATA_DIR,
    "step2_prompt_templates.json",
)
HANDDRAWN_STORYBOARD_RULES_PATH = os.path.join(
    REPO_ROOT,
    "templates",
    "prompts",
    "storyboard_rules_handdrawn.zh.md",
)
STEP2_PROMPT_TEMPLATE_FILES = {
    "script_system": os.path.join(
        REPO_ROOT,
        "templates",
        "prompts",
        "step2_script_system.md",
    ),
    "script_output_example": os.path.join(
        REPO_ROOT,
        "templates",
        "prompts",
        "step2_script_output_example.json",
    ),
    "visual_system": os.path.join(
        REPO_ROOT,
        "templates",
        "prompts",
        "step2_visual_system.md",
    ),
    "visual_output_example": os.path.join(
        REPO_ROOT,
        "templates",
        "prompts",
        "step2_visual_output_example.json",
    ),
}
STEP2_PROMPTS_FILE = "step2_prompts.json"
STEP2_SCRIPT_PLAN_FILE = "slide_script_plan.json"
STEP2_VISUAL_PLAN_FILE = "slide_visual_plan.json"
STEP2_LLM_TIMEOUT_SEC = 240.0


def _not_configured(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("Storyboard dependencies have not been configured")


clean_json_markdown: Callable[..., Any] = _not_configured
contract_slide_ids_from_payload: Callable[..., Any] = _not_configured
get_openai_client: Callable[..., Any] = _not_configured
handle_step_navigation: Callable[..., Any] = _not_configured
invalidate_after_upstream_edit: Callable[..., Any] = _not_configured
is_timeout_exception: Callable[..., Any] = _not_configured
mark_step_retry_needed: Callable[..., Any] = _not_configured
narration_dedupe_key: Callable[..., Any] = _not_configured
normalize_visual_contract: Callable[..., Any] = _not_configured
normalized_template_name: Callable[..., Any] = _not_configured
parse_int_setting: Callable[..., Any] = _not_configured
parse_json_or_repair_with_llm: Callable[..., Any] = _not_configured
parse_range_text: Callable[..., Any] = _not_configured
read_json_file: Callable[..., Any] = _not_configured
read_project_article_source: Callable[..., Any] = _not_configured
sync_narration_beats_to_contract: Callable[..., Any] = _not_configured
sync_narration_sources_from_contract: Callable[..., Any] = _not_configured
sync_reveal_manifest_to_contract: Callable[..., Any] = _not_configured
template_timestamp: Callable[..., Any] = _not_configured
write_project_log: Callable[..., Any] = _not_configured

AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION = ""
LEGACY_STEP2_PROMPT_HASHES: dict[str, set[str]] = {}
LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH = ""


@dataclass(frozen=True)
class StoryboardDependencies:
    clean_json_markdown: Callable[..., Any]
    contract_slide_ids_from_payload: Callable[..., Any]
    get_openai_client: Callable[..., Any]
    handle_step_navigation: Callable[..., Any]
    invalidate_after_upstream_edit: Callable[..., Any]
    is_timeout_exception: Callable[..., Any]
    mark_step_retry_needed: Callable[..., Any]
    narration_dedupe_key: Callable[..., Any]
    normalize_visual_contract: Callable[..., Any]
    normalized_template_name: Callable[..., Any]
    parse_int_setting: Callable[..., Any]
    parse_json_or_repair_with_llm: Callable[..., Any]
    parse_range_text: Callable[..., Any]
    read_json_file: Callable[..., Any]
    read_project_article_source: Callable[..., Any]
    sync_narration_beats_to_contract: Callable[..., Any]
    sync_narration_sources_from_contract: Callable[..., Any]
    sync_reveal_manifest_to_contract: Callable[..., Any]
    template_timestamp: Callable[..., Any]
    write_project_log: Callable[..., Any]
    ai_knowledge_script_extension: str
    legacy_prompt_hashes: dict[str, set[str]]
    legacy_interview_script_prompt_hash: str


_DEPENDENCIES: StoryboardDependencies | None = None


def configure_storyboard_dependencies(
    dependencies: StoryboardDependencies,
) -> None:
    global _DEPENDENCIES
    global AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION
    global LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH
    global LEGACY_STEP2_PROMPT_HASHES
    global clean_json_markdown
    global contract_slide_ids_from_payload
    global get_openai_client
    global handle_step_navigation
    global invalidate_after_upstream_edit
    global is_timeout_exception
    global mark_step_retry_needed
    global narration_dedupe_key
    global normalize_visual_contract
    global normalized_template_name
    global parse_int_setting
    global parse_json_or_repair_with_llm
    global parse_range_text
    global read_json_file
    global read_project_article_source
    global sync_narration_beats_to_contract
    global sync_narration_sources_from_contract
    global sync_reveal_manifest_to_contract
    global template_timestamp
    global write_project_log

    _DEPENDENCIES = dependencies
    clean_json_markdown = dependencies.clean_json_markdown
    contract_slide_ids_from_payload = (
        dependencies.contract_slide_ids_from_payload
    )
    get_openai_client = dependencies.get_openai_client
    handle_step_navigation = dependencies.handle_step_navigation
    invalidate_after_upstream_edit = (
        dependencies.invalidate_after_upstream_edit
    )
    is_timeout_exception = dependencies.is_timeout_exception
    mark_step_retry_needed = dependencies.mark_step_retry_needed
    narration_dedupe_key = dependencies.narration_dedupe_key
    normalize_visual_contract = dependencies.normalize_visual_contract
    normalized_template_name = dependencies.normalized_template_name
    parse_int_setting = dependencies.parse_int_setting
    parse_json_or_repair_with_llm = (
        dependencies.parse_json_or_repair_with_llm
    )
    parse_range_text = dependencies.parse_range_text
    read_json_file = dependencies.read_json_file
    read_project_article_source = (
        dependencies.read_project_article_source
    )
    sync_narration_beats_to_contract = (
        dependencies.sync_narration_beats_to_contract
    )
    sync_narration_sources_from_contract = (
        dependencies.sync_narration_sources_from_contract
    )
    sync_reveal_manifest_to_contract = (
        dependencies.sync_reveal_manifest_to_contract
    )
    template_timestamp = dependencies.template_timestamp
    write_project_log = dependencies.write_project_log
    AI_KNOWLEDGE_STEP2_SCRIPT_EXTENSION = (
        dependencies.ai_knowledge_script_extension
    )
    LEGACY_STEP2_PROMPT_HASHES = dependencies.legacy_prompt_hashes
    LEGACY_INTERVIEW_SCRIPT_PROMPT_HASH = (
        dependencies.legacy_interview_script_prompt_hash
    )

def storyboard_rules_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", "storyboard_rules.txt")


def storyboard_profile_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", "pipeline_profile.yaml")


def visual_contract_schema_text() -> str:
    schema_path = os.path.join(REPO_ROOT, "schemas", "visual_contract.schema.json")
    if not os.path.exists(schema_path):
        return ""
    with open(schema_path, "r", encoding="utf-8") as f:
        return f.read()


def default_storyboard_profile_text() -> str:
    profile_path = os.path.join(REPO_ROOT, "config", "pipeline_profiles.yaml")
    with open(profile_path, "r", encoding="utf-8-sig") as f:
        return f.read()


def sanitize_storyboard_profile(profile: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = copy.deepcopy(profile)
    storyboard = sanitized.get("storyboard")
    if not isinstance(storyboard, dict):
        return sanitized
    default_storyboard = read_pipeline_profile().get("storyboard", {})
    default_roles = default_storyboard.get("roles", {}) if isinstance(default_storyboard, dict) else {}
    roles = storyboard.get("roles")
    if isinstance(roles, dict):
        # Page subtitles are no longer part of the production contract. Drop
        # legacy editable role definitions instead of letting an old template
        # reintroduce subtitle groups into Step 2.
        roles.pop("subtitle", None)
        for role, config in roles.items():
            if not isinstance(config, dict):
                continue
            config.pop("required", None)
            config.pop("speak_policy", None)
            description = str(config.get("description") or "")
            if any(marker in description for marker in ("只展示不朗读", "不绑定旁白", "可选副标题", "可选总结区")):
                default_config = default_roles.get(role, {}) if isinstance(default_roles, dict) else {}
                fallback_descriptions = {
                    "decoration": "装饰元素，只在确实帮助理解画面时使用。",
                }
                config["description"] = str(default_config.get("description") or fallback_descriptions.get(role) or description)

    structure_rules = storyboard.get("structure_rules")
    if isinstance(structure_rules, list):
        legacy_markers = (
            "speak_policy",
            "display_only",
            "可讲解的 visual_group",
            "旁白讲解",
            "必选结构",
            "可选结构",
        )
        retained_rules = [
            rule for rule in structure_rules
            if not any(marker in str(rule) for marker in legacy_markers)
        ]
        default_rules = default_storyboard.get("structure_rules", []) if isinstance(default_storyboard, dict) else []
        for rule in default_rules if isinstance(default_rules, list) else []:
            if rule not in retained_rules:
                retained_rules.append(rule)
        storyboard["structure_rules"] = retained_rules
    return sanitized


def parse_storyboard_profile_text(profile_text: str) -> Dict[str, Any]:
    try:
        profile = yaml.safe_load(profile_text) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=400, detail=f"分镜结构 YAML 格式错误: {exc}") from exc
    if not isinstance(profile, dict):
        raise HTTPException(status_code=400, detail="分镜结构配置必须是 YAML 对象")
    storyboard = profile.get("storyboard")
    if not isinstance(storyboard, dict):
        raise HTTPException(status_code=400, detail="分镜结构配置缺少 storyboard 对象")
    roles = storyboard.get("roles")
    if not isinstance(roles, dict) or not roles:
        raise HTTPException(status_code=400, detail="分镜结构配置至少需要一个 storyboard.roles 角色")
    return sanitize_storyboard_profile(profile)


def storyboard_profile_editor_data(profile: Dict[str, Any]) -> Dict[str, Any]:
    profile = sanitize_storyboard_profile(profile)
    storyboard = profile.get("storyboard") if isinstance(profile.get("storyboard"), dict) else {}
    roles = storyboard.get("roles") if isinstance(storyboard.get("roles"), dict) else {}
    return {
        "slide_count": copy.deepcopy(storyboard.get("slide_count") or {}),
        "visual_group_count": copy.deepcopy(storyboard.get("visual_group_count") or {}),
        "roles": {
            str(role): {
                "label": str(config.get("label") or role),
                "description": str(config.get("description") or ""),
                "enabled": config.get("enabled") is not False,
            }
            for role, config in roles.items()
            if isinstance(config, dict)
        },
        "protected_fields": [
            "slide_id",
            "visual_groups",
            "narration_beats",
            "visual_groups[].id",
            "visual_groups[].content_unit_id",
            "narration_beats[].group_id",
            "narration_beats[].content_unit_id",
        ],
    }


def apply_storyboard_profile_patch(
    profile: Dict[str, Any],
    patch: Any,
) -> Dict[str, Any]:
    if not isinstance(patch, dict):
        return sanitize_storyboard_profile(profile)
    merged = copy.deepcopy(profile)
    storyboard = merged.setdefault("storyboard", {})
    if not isinstance(storyboard, dict):
        raise HTTPException(status_code=400, detail="storyboard 必须是 YAML 对象")

    for field in ("slide_count", "visual_group_count"):
        value = patch.get(field)
        if value is None:
            continue
        if not isinstance(value, dict):
            raise HTTPException(status_code=400, detail=f"{field} 必须是对象")
        existing = storyboard.get(field)
        if not isinstance(existing, dict):
            existing = {}
        for size_key in ("short_article", "medium_article", "long_article"):
            if size_key in value:
                text = str(value.get(size_key) or "").strip()
                if not text:
                    raise HTTPException(status_code=400, detail=f"{field}.{size_key} 不能为空")
                existing[size_key] = text
        storyboard[field] = existing

    role_patch = patch.get("roles")
    if role_patch is not None:
        if not isinstance(role_patch, dict):
            raise HTTPException(status_code=400, detail="roles 必须是对象")
        current_roles = storyboard.get("roles")
        if not isinstance(current_roles, dict):
            current_roles = {}
        updated_roles: Dict[str, Any] = {}
        for role, current_config in current_roles.items():
            if not isinstance(current_config, dict):
                continue
            next_config = copy.deepcopy(current_config)
            next_config.pop("required", None)
            next_config.pop("speak_policy", None)
            next_patch = role_patch.get(role)
            if not isinstance(next_patch, dict):
                updated_roles[role] = next_config
                continue
            next_config["enabled"] = next_patch.get("enabled") is not False
            updated_roles[role] = next_config
        if not any(config.get("enabled") is not False for config in updated_roles.values()):
            raise HTTPException(status_code=400, detail="至少需要启用一个分镜结构类型")
        storyboard["roles"] = updated_roles
    return parse_storyboard_profile_text(
        yaml.safe_dump(merged, allow_unicode=True, sort_keys=False, width=1000)
    )


def read_project_pipeline_profile(project: Project) -> Dict[str, Any]:
    path = storyboard_profile_path(project)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8-sig") as f:
            return parse_storyboard_profile_text(f.read())
    return read_pipeline_profile()


def default_storyboard_rules() -> str:
    default_path = os.path.join(REPO_ROOT, "templates", "prompts", "storyboard_rules.zh.md")
    if os.path.exists(default_path):
        with open(default_path, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "旁白自然口语化；每个旁白语段只绑定一个清晰的视觉分组；画面先于对应语音约 1 秒出现。"


def handdrawn_storyboard_rules() -> str:
    if os.path.exists(HANDDRAWN_STORYBOARD_RULES_PATH):
        with open(HANDDRAWN_STORYBOARD_RULES_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    return default_storyboard_rules()


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


def stable_plan_id(value: Any, prefix: str, index: int) -> str:
    text = re.sub(r"[^a-zA-Z0-9_\\-]+", "_", str(value or "").strip())
    return text or f"{prefix}_{index:03d}"


def clean_planning_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def clean_planning_block(value: Any) -> str:
    if isinstance(value, list):
        parts = [clean_planning_text(item) for item in value]
        return "\n".join(part for part in parts if part)
    if isinstance(value, dict):
        parts = [clean_planning_text(item) for item in value.values()]
        return "\n".join(part for part in parts if part)
    return "\n".join(
        line
        for line in (clean_planning_text(line) for line in str(value or "").replace("\r", "\n").split("\n"))
        if line
    )


def normalize_slide_body(slide: Dict[str, Any]) -> str:
    body = clean_planning_block(slide.get("body") or slide.get("body_content") or slide.get("core_message"))
    if body:
        return body
    return "\n".join(point["text"] for point in normalize_body_points(slide.get("body_points")) if point.get("text"))


def normalize_body_points(value: Any, fallback_body: str = "") -> List[Dict[str, str]]:
    points = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    for index, point in enumerate(points, start=1):
        if isinstance(point, dict):
            text = clean_planning_text(point.get("text") or point.get("content") or "")
            purpose = clean_planning_text(point.get("purpose") or "")
            point_id = stable_plan_id(point.get("point_id"), "point", index)
        else:
            text = clean_planning_text(point)
            purpose = ""
            point_id = f"point_{index:03d}"
        if not text:
            continue
        normalized.append({"point_id": point_id, "text": text, "purpose": purpose})
    if not normalized and fallback_body:
        normalized.append({"point_id": "point_001", "text": clean_planning_text(fallback_body), "purpose": "正文"})
    return normalized


def normalize_narration_segments(value: Any, fallback_narration: str = "") -> List[Dict[str, str]]:
    segments = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    seen_narration: set[str] = set()
    previous_narration = ""
    for index, segment in enumerate(segments, start=1):
        if isinstance(segment, dict):
            narration = clean_planning_text(segment.get("narration") or segment.get("spoken_text") or "")
            purpose = clean_planning_text(segment.get("purpose") or segment.get("spoken_intent") or "")
            segment_id = stable_plan_id(segment.get("segment_id"), "seg", index)
        else:
            narration = clean_planning_text(segment)
            purpose = ""
            segment_id = f"seg_{index:03d}"
        if not narration or narration == previous_narration:
            continue
        narration_key = narration_dedupe_key(narration)
        if narration_key and narration_key in seen_narration:
            continue
        if narration_key:
            seen_narration.add(narration_key)
        normalized.append({"segment_id": segment_id, "narration": narration, "purpose": purpose})
        previous_narration = narration
    fallback_narration = clean_planning_text(fallback_narration)
    if not normalized and fallback_narration:
        normalized.append({"segment_id": "seg_001", "narration": fallback_narration, "purpose": "完整演讲稿"})
    return normalized


def normalize_slide_script_plan(plan: Dict[str, Any], project_title: str) -> Dict[str, Any]:
    slides = plan.get("slides") if isinstance(plan, dict) else []
    if not isinstance(slides, list) or not slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_script_plan.slides")
    normalized_slides: List[Dict[str, Any]] = []
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            continue
        slide_id = stable_plan_id(slide.get("slide_id"), "slide", index)
        if not slide_id.startswith("slide_"):
            slide_id = f"slide_{index:03d}"
        narration = clean_planning_text(
            slide.get("narration")
            or slide.get("speech")
            or slide.get("script")
            or " ".join(
                clean_planning_text(segment.get("narration") if isinstance(segment, dict) else segment)
                for segment in (slide.get("narration_segments") or [])
            )
        )
        if not narration:
            raise HTTPException(status_code=500, detail=f"{slide_id} 缺少 narration")
        slide_title = clean_planning_text(slide.get("slide_title") or slide.get("title") or f"第 {index} 页")
        normalized_slides.append(
            {
                "slide_id": slide_id,
                "slide_title": slide_title,
                "narration": narration,
            }
        )
    if not normalized_slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_script_plan.slides")
    return {"title": str(plan.get("title") or project_title).strip() or project_title, "slides": normalized_slides}


def normalize_visual_elements(value: Any) -> List[Dict[str, str]]:
    elements = value if isinstance(value, list) else []
    normalized: List[Dict[str, str]] = []
    for index, element in enumerate(elements, start=1):
        if not isinstance(element, dict):
            continue
        role = str(element.get("role") or "body").strip().lower()
        if role in {"content_body", "body_content"}:
            role = "body"
        visual_description = clean_planning_text(
            element.get("visual_description")
            or element.get("visible_text")
            or element.get("text")
            or ""
        )
        narration = clean_planning_text(element.get("narration") or "")
        visual_type = normalize_visual_type(element.get("visual_type"), has_text=bool(visual_description))
        if not visual_description:
            continue
        normalized.append(
            {
                "element_id": stable_plan_id(element.get("element_id"), "el", index),
                "role": role,
                "visual_type": visual_type,
                "visual_description": visual_description,
                "narration": narration,
            }
        )
    return normalized


def narration_sequence_key(value: Any) -> str:
    """Compare Step A narration with Step B fragments without hiding punctuation changes."""
    return re.sub(r"\s+", "", clean_planning_text(value))


def validate_slide_visual_mapping(
    slide_id: str,
    elements: List[Dict[str, str]],
    script_slide: Optional[Dict[str, Any]] = None,
) -> None:
    title_elements = [element for element in elements if element.get("role") == "title"]
    body_elements = [element for element in elements if element.get("role") == "body"]
    unsupported_roles = sorted({
        str(element.get("role") or "")
        for element in elements
        if element.get("role") not in {"title", "body"}
    })
    if unsupported_roles:
        raise HTTPException(
            status_code=500,
            detail=(
                f"{slide_id} 包含不参与一对一旁白映射的 role: {', '.join(unsupported_roles)}。"
                "系统不使用页面副标题；装饰由生图阶段处理，visual_elements 只能包含 title 和 body。"
            ),
        )
    if len(title_elements) != 1 or not elements or elements[0].get("role") != "title":
        raise HTTPException(status_code=500, detail=f"{slide_id} 必须以且仅以一个 title 元素开头")
    if not body_elements:
        raise HTTPException(status_code=500, detail=f"{slide_id} 至少需要一个 body 视觉元素")
    title = title_elements[0]
    if title.get("visual_type") != "text":
        raise HTTPException(status_code=500, detail=f"{slide_id} 的 title 必须使用 text 形式")
    for element in elements:
        if not str(element.get("narration") or "").strip():
            raise HTTPException(
                status_code=500,
                detail=f"{slide_id} 的 {element.get('element_id') or 'visual element'} 没有对应演讲片段",
            )
    if not isinstance(script_slide, dict):
        return
    expected_title = clean_planning_text(script_slide.get("slide_title") or "")
    if expected_title and clean_planning_text(title.get("visual_description")) != expected_title:
        raise HTTPException(
            status_code=500,
            detail=f"{slide_id} 的标题画面文字必须逐字等于 slide_title: {expected_title}",
        )
    source_narration = clean_planning_text(script_slide.get("narration") or "")
    combined_narration = "".join(str(element.get("narration") or "") for element in elements)
    if narration_sequence_key(combined_narration) != narration_sequence_key(source_narration):
        raise HTTPException(
            status_code=500,
            detail=(
                f"{slide_id} 的视觉元素演讲片段未能完整还原 Step A 演讲稿。"
                "每个片段必须非空、连续、无遗漏、无重复且保持原顺序。"
            ),
        )


def normalize_slide_visual_plan(
    plan: Dict[str, Any],
    script_plan: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    slides = plan.get("slides") if isinstance(plan, dict) else []
    if not isinstance(slides, list) or not slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_visual_plan.slides")
    script_by_id = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in ((script_plan or {}).get("slides") or [])
        if isinstance(slide, dict)
    }
    normalized_slides: List[Dict[str, Any]] = []
    for index, slide in enumerate(slides, start=1):
        if not isinstance(slide, dict):
            continue
        slide_id = stable_plan_id(slide.get("slide_id"), "slide", index)
        if not slide_id.startswith("slide_"):
            slide_id = f"slide_{index:03d}"
        elements = normalize_visual_elements(slide.get("visual_elements"))
        if not elements:
            raise HTTPException(status_code=500, detail=f"{slide_id} 缺少 visual_elements")
        validate_slide_visual_mapping(slide_id, elements, script_by_id.get(slide_id))
        normalized_slides.append({"slide_id": slide_id, "visual_elements": elements})
    if not normalized_slides:
        raise HTTPException(status_code=500, detail="AI 没有返回可用的 slide_visual_plan.slides")
    return {"slides": normalized_slides}


def read_plan_json(path: str, missing_message: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=missing_message)
    with open(path, "r", encoding="utf-8-sig") as f:
        value = json.load(f)
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="规划文件格式无效")
    return value


def configured_step2_llm() -> tuple[str, Optional[str], str, float, int]:
    llm_api_key = get_setting("llm_api_key")
    llm_base_url = get_setting("llm_base_url")
    llm_model = get_setting("llm_model")
    llm_temp = float(get_setting("llm_temperature", "0.7"))
    planning_temp = min(llm_temp, 0.2)
    planning_max_tokens = parse_int_setting(get_setting("llm_max_tokens", "50000"), 50000, 1024, 64000)
    if not llm_api_key:
        raise HTTPException(status_code=400, detail="未配置大模型 API 密钥，请在系统设置中配置后再试。")
    return llm_api_key, llm_base_url, llm_model, planning_temp, planning_max_tokens


def step2_llm_vendor_options(model: str, base_url: Optional[str]) -> Dict[str, Any]:
    """Use fast non-thinking mode for Volcengine/Doubao storyboard requests."""
    model_name = str(model or "").strip().lower()
    endpoint = str(base_url or "").strip().lower()
    if model_name.startswith("doubao-") or "volces.com" in endpoint:
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {}


def run_step2_json_llm(
    *,
    project: Project,
    system_prompt: str,
    user_prompt: str,
    artifact_prefix: str,
    schema_hint: str,
    trace_id: str,
) -> Dict[str, Any]:
    llm_api_key, llm_base_url, llm_model, planning_temp, planning_max_tokens = configured_step2_llm()
    stage_label = {
        "step2_script_plan": "Step 2A 演讲稿规划",
        "step2_visual_plan": "Step 2B 可视化规划",
    }.get(artifact_prefix, "Step 2 分镜规划")
    started_at = time.monotonic()
    vendor_options = step2_llm_vendor_options(llm_model, llm_base_url)
    write_project_log(
        project,
        f"{artifact_prefix}_start",
        trace_id=trace_id,
        model=llm_model,
        base_url=llm_base_url,
        max_tokens=planning_max_tokens,
        thinking_disabled=bool(vendor_options),
    )
    client = get_openai_client(
        api_key=llm_api_key,
        base_url=llm_base_url,
        timeout=STEP2_LLM_TIMEOUT_SEC,
        max_retries=0,
    )
    try:
        try:
            response = client.chat.completions.create(
                model=llm_model,
                temperature=planning_temp,
                max_tokens=planning_max_tokens,
                timeout=STEP2_LLM_TIMEOUT_SEC,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                **vendor_options,
            )
        except Exception as inner_e:
            if is_timeout_exception(inner_e):
                raise
            logger.warning("Failed LLM call with response_format for %s, retrying without it: %s", artifact_prefix, inner_e)
            response = client.chat.completions.create(
                model=llm_model,
                temperature=planning_temp,
                max_tokens=planning_max_tokens,
                timeout=STEP2_LLM_TIMEOUT_SEC,
                messages=[
                    {"role": "system", "content": system_prompt + " 请只输出纯 JSON，不要包含 Markdown 代码块标记（如 ```json ）。"},
                    {"role": "user", "content": user_prompt},
                ],
                **vendor_options,
            )
        choice = response.choices[0]
        logger.info("%s finish_reason=%s usage=%s", artifact_prefix, getattr(choice, "finish_reason", None), getattr(response, "usage", None))
        content_str = str(choice.message.content or "").strip()
        if not content_str:
            raise ValueError("大模型返回了空内容")
        cleaned_content = clean_json_markdown(content_str)
        return parse_json_or_repair_with_llm(
            cleaned_content=cleaned_content,
            raw_content=content_str,
            client=client,
            model=llm_model,
            run_dir=project.run_dir,
            artifact_prefix=artifact_prefix,
            schema_hint=schema_hint,
            max_tokens=planning_max_tokens,
        )
    except HTTPException as exc:
        write_project_log(
            project,
            f"{artifact_prefix}_failed",
            trace_id=trace_id,
            elapsed_sec=round(time.monotonic() - started_at, 2),
            status_code=exc.status_code,
            error=str(exc.detail),
        )
        raise
    except Exception as exc:
        timed_out = is_timeout_exception(exc)
        write_project_log(
            project,
            f"{artifact_prefix}_failed",
            trace_id=trace_id,
            elapsed_sec=round(time.monotonic() - started_at, 2),
            timeout=timed_out,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        if timed_out:
            raise HTTPException(
                status_code=504,
                detail=f"{stage_label}超过 {int(STEP2_LLM_TIMEOUT_SEC)} 秒仍未返回，请重试或切换响应更快的模型。",
            ) from exc
        raise HTTPException(status_code=502, detail=f"{stage_label}失败：{str(exc)[:300]}") from exc
    finally:
        try:
            client.close()
        except Exception:
            pass


def script_plan_schema_hint() -> str:
    return read_prompt_template(STEP2_PROMPT_TEMPLATE_FILES["script_output_example"])


def visual_plan_schema_hint() -> str:
    return read_prompt_template(STEP2_PROMPT_TEMPLATE_FILES["visual_output_example"])


def build_step2_script_user_prompt(
    *,
    project_title: str,
    article_content: str,
    generation_requirement: str,
) -> str:
    user_input = {
        "project_title": project_title,
        "article_content": article_content,
    }
    if str(generation_requirement or "").strip():
        user_input["generation_requirement"] = str(generation_requirement).strip()
    return json.dumps(user_input, ensure_ascii=False, indent=2)


def build_step2_visual_user_prompt(script_plan: Dict[str, Any]) -> str:
    minimal_script_plan = {
        "title": str(script_plan.get("title") or "").strip(),
        "slides": [
            {
                "slide_id": str(slide.get("slide_id") or "").strip(),
                "slide_title": str(slide.get("slide_title") or "").strip(),
                "narration": str(slide.get("narration") or "").strip(),
            }
            for slide in (script_plan.get("slides") or [])
            if isinstance(slide, dict)
        ],
    }
    return json.dumps({"slide_script_plan": minimal_script_plan}, ensure_ascii=False, indent=2)


def element_visible_text(element: Dict[str, str], index: int) -> str:
    description = str(element.get("visual_description") or "").strip()
    if description:
        return description[:32]
    return f"视觉元素 {index}"


def compose_visual_contract_from_plans(
    script_plan: Dict[str, Any],
    visual_plan: Dict[str, Any],
    project_id: str,
    project_title: str,
) -> Dict[str, Any]:
    script_slides = script_plan.get("slides") if isinstance(script_plan, dict) else []
    visual_slides = visual_plan.get("slides") if isinstance(visual_plan, dict) else []
    if not isinstance(script_slides, list) or not script_slides:
        raise HTTPException(status_code=400, detail="slide_script_plan.json 缺少 slides")
    if not isinstance(visual_slides, list) or not visual_slides:
        raise HTTPException(status_code=400, detail="slide_visual_plan.json 缺少 slides")

    visual_by_id = {
        str(slide.get("slide_id") or "").strip(): slide
        for slide in visual_slides
        if isinstance(slide, dict)
    }
    subtitle_policy = "no_slides_have_subtitle"
    slides: List[Dict[str, Any]] = []
    for slide_index, script_slide in enumerate(script_slides, start=1):
        if not isinstance(script_slide, dict):
            continue
        slide_id = str(script_slide.get("slide_id") or f"slide_{slide_index:03d}").strip()
        visual_slide = visual_by_id.get(slide_id)
        if not isinstance(visual_slide, dict):
            raise HTTPException(status_code=400, detail=f"{slide_id} 缺少对应的 visual plan")
        body_points = script_slide.get("body_points") if isinstance(script_slide.get("body_points"), list) else []
        visual_groups: List[Dict[str, Any]] = []
        narration_beats: List[Dict[str, Any]] = []
        for element_index, element in enumerate(visual_slide.get("visual_elements") or [], start=1):
            if not isinstance(element, dict):
                continue
            element_id = stable_plan_id(element.get("element_id"), "el", element_index)
            group_id = f"{slide_id}_{element_id}"
            content_unit_id = f"{slide_id}_unit_{element_index:03d}"
            role = str(element.get("role") or "body").strip().lower()
            role = "decoration" if role == "decoration" else ("title" if role == "title" else ("subtitle" if role == "subtitle" else "content_body"))
            visible_text = element_visible_text(element, element_index)
            description = str(element.get("visual_description") or visible_text).strip()
            narration = str(element.get("narration") or "").strip()
            narration_function_value = str(element.get("narration_function") or element.get("visual_description") or visible_text or "").strip()
            visual_type = normalize_visual_type(element.get("visual_type"))
            display_text = description if visual_type == "text" else ""
            group = {
                "id": group_id,
                "element_id": element_id,
                "role": role,
                "visible_text": visible_text,
                "display_text": display_text,
                "visual_anchor": description,
                "narration_function": narration_function_value,
                "reveal_order": element_index,
                "content_unit_id": content_unit_id,
                "mask_target": description,
                "visual_type": visual_type,
            }
            visual_groups.append(group)
            if narration:
                narration_beats.append(
                    {
                        "id": f"{slide_id}_beat_{len(narration_beats) + 1:03d}",
                        "group_id": group_id,
                        "visible_anchor": visible_text,
                        "spoken_intent": narration_function_value,
                        "spoken_text": narration,
                        "content_unit_id": content_unit_id,
                    }
                )
        if not visual_groups:
            raise HTTPException(status_code=400, detail=f"{slide_id} 没有可合成的 visual elements")
        if not narration_beats:
            raise HTTPException(status_code=400, detail=f"{slide_id} 没有可合成的 narration beats")
        body_content = [
            str(point.get("text") or "").strip()
            for point in body_points
            if isinstance(point, dict) and point.get("text")
        ]
        if not body_content and str(script_slide.get("body") or "").strip():
            body_content = [str(script_slide.get("body") or "").strip()]
        if not body_content:
            body_content = [
                str(group.get("visible_text") or "").strip()
                for group in visual_groups
                if group.get("role") == "content_body" and str(group.get("visible_text") or "").strip()
            ]
        slides.append(
            {
                "slide_id": slide_id,
                "main_title": str(script_slide.get("slide_title") or f"第 {slide_index} 页").strip(),
                "subtitle": "",
                "core_message": "；".join(body_content),
                "body_content": body_content,
                "visual_groups": visual_groups,
                "narration_beats": narration_beats,
            }
        )
    return {
        "version": "visual_contract_v1",
        "presentation_policy": {
            "subtitle_policy": subtitle_policy,
            "subtitle_decided_by": "system_no_subtitle_contract",
            "visual_narration_mapping": "one_visual_element_to_one_narration_beat_v1",
        },
        "topic": {
            "topic_id": "topic_" + project_id,
            "topic_name": project_title,
            "topic_summary": "",
        },
        "slides": slides,
    }


def storyboard_template_payload(
    template_id: str,
    name: str,
    rules: str,
    profile_text: str,
    built_in: bool = False,
    updated_at: str = "",
) -> Dict[str, Any]:
    profile = parse_storyboard_profile_text(profile_text)
    return {
        "id": template_id,
        "name": name,
        "built_in": built_in,
        "updated_at": updated_at,
        "rules": rules,
        "profile_yaml": profile_text,
        "roles": role_catalog(profile),
        "editor": storyboard_profile_editor_data(profile),
    }


def list_storyboard_templates() -> List[Dict[str, Any]]:
    templates = [
        storyboard_template_payload(
            "default",
            "内容优先通用分镜模板",
            default_storyboard_rules(),
            default_storyboard_profile_text(),
            built_in=True,
        ),
        storyboard_template_payload(
            "handdrawn_explainer",
            "手绘科普内容优先模板",
            handdrawn_storyboard_rules(),
            default_storyboard_profile_text(),
            built_in=True,
        ),
    ]
    stored = read_json_file(STORYBOARD_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        return templates
    for item in stored:
        if not isinstance(item, dict):
            continue
        try:
            templates.append(
                storyboard_template_payload(
                    str(item.get("id") or ""),
                    str(item.get("name") or ""),
                    str(item.get("rules") or ""),
                    str(item.get("profile_yaml") or ""),
                    updated_at=str(item.get("updated_at") or ""),
                )
            )
        except HTTPException as exc:
            logger.warning("Skipping invalid storyboard template %s: %s", item.get("id"), exc.detail)
    return templates


def get_storyboard_templates():
    return {"success": True, "templates": list_storyboard_templates()}


def save_storyboard_template(payload: Dict[str, Any]):
    name = normalized_template_name(payload.get("name"))
    protected_names = {"默认分镜模板", "内容优先通用分镜模板", "手绘科普内容优先模板"}
    if name.casefold() in {item.casefold() for item in protected_names}:
        raise HTTPException(status_code=400, detail="内置分镜模板名称不可覆盖")
    rules = str(payload.get("rules") or "").strip() or default_storyboard_rules()
    profile_text = str(payload.get("profile_yaml") or "").strip() or default_storyboard_profile_text()
    profile = parse_storyboard_profile_text(profile_text)
    profile = apply_storyboard_profile_patch(profile, payload.get("profile_patch"))
    profile_text = yaml.safe_dump(profile, allow_unicode=True, sort_keys=False, width=1000).strip()

    stored = read_json_file(STORYBOARD_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        stored = []
    existing = next(
        (
            item
            for item in stored
            if isinstance(item, dict)
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
            "rules": rules,
            "profile_yaml": profile_text,
            "updated_at": now,
        }
    )
    write_json_atomic(STORYBOARD_TEMPLATES_PATH, stored)
    return {
        "success": True,
        "template": storyboard_template_payload(
            str(existing["id"]),
            name,
            rules,
            profile_text,
            updated_at=now,
        ),
        "templates": list_storyboard_templates(),
    }


def delete_storyboard_template(template_id: str):
    if template_id == "default":
        raise HTTPException(status_code=400, detail="内置分镜模板不能删除")
    if not re.fullmatch(r"[0-9a-f]{12}", template_id):
        raise HTTPException(status_code=404, detail="分镜模板不存在")
    stored = read_json_file(STORYBOARD_TEMPLATES_PATH, [])
    if not isinstance(stored, list):
        stored = []
    next_stored = [
        item
        for item in stored
        if not (isinstance(item, dict) and str(item.get("id") or "") == template_id)
    ]
    if len(next_stored) == len(stored):
        raise HTTPException(status_code=404, detail="分镜模板不存在")
    write_json_atomic(STORYBOARD_TEMPLATES_PATH, next_stored)
    return {"success": True, "templates": list_storyboard_templates()}


def build_storyboard_request(
    project_title: str,
    article_summary: str,
    article_content: str,
    storyboard_rules: str,
    profile: Optional[Dict[str, Any]] = None,
) -> tuple[str, str]:
    profile = profile or read_pipeline_profile()
    slide_count_requirement, _ = storyboard_requirements(article_content, profile)
    profile_prompt = storyboard_profile_prompt(article_content, profile)

    schema_hint = visual_contract_schema_text()

    system_prompt = f"""你是一个顶级的 PPT 视频分镜策划师和演讲稿设计师。

## 目的
把文章转成可直接驱动后续生图、Mask、Reveal、旁白和视频制作的 Visual Contract；忠实保留文章事实，不在本阶段生成图片或执行动画。

## 输入
- 项目主题、文章摘要与文章全文。
- 当前项目的分镜结构配置、用户自定义规则与 JSON Schema。
- 文章及显式规则是内容与边界依据；不得虚构来源中没有的具体事实。

## 输出
- 只返回一个符合下方 JSON Schema 的合法 JSON 对象。
- 不要 Markdown 代码围栏、解释、推理过程或任何 JSON 之外的文字。
- 输出必须同时满足 visual_groups 与 narration_beats 的绑定约束，供后续阶段直接读取。
请阅读用户输入的内容摘要和全文，先设计“如何把内容讲清楚”的理解路径和演讲稿，再把它编译成符合 PPT 动画视频制作标准的视觉合约(Visual Contract)。
视频的画面风格可由后续图片风格配置决定；这里重点规划“讲解逻辑、演讲稿、内容结构、视觉表达、旁白绑定、Mask 友好性”。
总原则：
- 内容优先，结构服务内容；不要让内容服务固定模板或角色枚举。
- 演讲稿不是附属品。每页必须有自然、连贯、适合口播的 spoken_text，用来解释推理过程、上下文和结论。
- 画面不是演讲稿的逐字复刻。visible_text 应是关键词、短句、结构标签、图示标签或结论钩子。
- visual_groups 是后续 Mask/动画/旁白绑定接口，不是页面设计模板；role 只是后处理语义标签。
- 主标题使用页面上方固定位置，不生成页面副标题；底部 y=930..1080 固定为视频字幕安全区。除此之外，主体内容区根据内容自由发挥。
- 字号比例必须明确：每页 slide 顶部标题的视觉字号为当前默认标题的 2 倍；正文内容、演讲稿对应画面文字的视觉字号约为当前默认的 2/3。
- 禁止画面元素重叠：文字、卡片、图标、箭头、线条、标签、装饰、图表之间不得互相覆盖、压住、穿插或粘连。
要求：
1. 必须要将整篇文章合理划分，分成 {slide_count_requirement} Slide（每页的 slide_id 为 slide_001, slide_002 格式）。
2. 视觉分组数量由内容和独立 Reveal 需求决定；一个完整正文视觉组同样合法，不设置固定上下限。不要固定套用“主标题/正文/总结”模板；可以按内容需要使用判断链、冲突地图、对象关系图、推理路径、时间压力图、对比、表格、流程、FAQ、场景拆解或行动清单。
3. 每个视觉分组（visual_groups）必须有：
   - id: 比如 title_group, body_group_01 等
   - visible_text: 页面上会显式画出来的中文字符标签（非常重要，通常为短句或关键词，绝对不能为空；不要把整段演讲稿塞进这里）
   - visual_anchor: 视觉描述（比如“顶部主标题”、“左侧判断链起点”、“中间对象关系图”、“右侧结论卡”）
   - narration_function: 解释该分组在画面中所起的视觉/解释作用
   - reveal_order: 页面渲染时层淡入淡出显示的顺序，从 1 开始依次增加
   - content_unit_id: 稳定内容单元 ID，必须和 narration_beats[].content_unit_id 对齐
   - mask_target: 后续人工 Mask 要覆盖的画面目标描述
4. 必须规划 narration_beats (旁白语段)，使说话声音与相应视觉分组绑定：
   - group_id: 指向前面定义的 visual_groups 中的 id
   - visible_anchor: 该分组对应的 visible_text 文本（不可写错，必须一致）
   - spoken_intent: 这一句话想达到的意图
   - spoken_text: 这一句话具体要朗读的中文旁白（需自然连贯，解释 visible_text）
   - content_unit_id: 必须与绑定 visual_group 的 content_unit_id 一致
   - narration_beats 是是否朗读的唯一依据：某个 visual_group 有对应 beat 才会在演讲稿中讲解，没有 beat 就只作为画面内容展示。
   - 不要为了覆盖所有 visual_groups 而强行补旁白；只为演讲稿实际需要讲解的内容创建 beat。
   - 同一页内每条 spoken_text 的内容必须唯一；严禁重复、近似复述或为了凑数量复制同一句旁白。
5. 当前项目的可配置分镜结构如下。请优先遵守：
{profile_prompt}
6. 用户自定义的分镜与演讲稿规则如下。请遵守这些内容，但不得修改输出字段、层级、ID 规则或 JSON 结构：
--- 用户分镜规则开始 ---
{storyboard_rules}
--- 用户分镜规则结束 ---
7. 请确保生成的 JSON 数据严格符合以下的 JSON Schema 格式要求：
{schema_hint}

请直接返回合法的 JSON 对象，不要包含 markdown 标记的 ```json 外壳。"""
    user_prompt = (
        f"项目主题：{project_title}\n"
        f"摘要提纲：{article_summary}\n"
        f"正文全文：\n{article_content}"
    )
    return system_prompt, user_prompt


def get_step2_rules(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    path = storyboard_rules_path(project)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            rules = f.read()
    else:
        rules = default_storyboard_rules()
    profile_path = storyboard_profile_path(project)
    if os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8-sig") as f:
            profile_text = f.read()
    else:
        profile_text = default_storyboard_profile_text()
    profile = parse_storyboard_profile_text(profile_text)
    return {
        "success": True,
        "rules": rules,
        "profile_yaml": profile_text,
        "schema_text": visual_contract_schema_text(),
        "roles": role_catalog(profile),
        "editor": storyboard_profile_editor_data(profile),
    }


def update_step2_rules(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    rules = str(payload.get("rules") or "").strip()
    if not rules:
        rules = default_storyboard_rules()
    profile_text = str(payload.get("profile_yaml") or "").strip()
    if not profile_text:
        profile_text = default_storyboard_profile_text().strip()
    profile = parse_storyboard_profile_text(profile_text)
    profile = apply_storyboard_profile_patch(profile, payload.get("profile_patch"))
    profile_text = yaml.safe_dump(
        profile,
        allow_unicode=True,
        sort_keys=False,
        width=1000,
    ).strip()
    path = storyboard_rules_path(project)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(rules + "\n")
    with open(storyboard_profile_path(project), "w", encoding="utf-8", newline="\n") as f:
        f.write(profile_text.rstrip() + "\n")
    return {
        "success": True,
        "rules": rules,
        "profile_yaml": profile_text,
        "roles": role_catalog(profile),
        "editor": storyboard_profile_editor_data(profile),
    }


def get_step2_prompts(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return step2_prompt_response(project)


def update_step2_prompts(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    defaults = default_step2_prompts()
    prompts: Dict[str, str] = {}
    for key, default_value in defaults.items():
        value = str(payload.get(key) or "").strip()
        prompts[key] = value or default_value
    write_json_atomic(step2_prompts_path(project), prompts)
    return step2_prompt_response(project)


def execute_step2_script_plan(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    article_source = read_project_article_source(project)
    project_title = article_source["title"]
    article_content = article_source["content"]
    generation_requirement = str((payload or {}).get("requirement") or "").strip()
    prompts = read_step2_prompts(project)
    if step2_script_prompt_uses_legacy_contract(prompts["script_system"]):
        raise HTTPException(
            status_code=409,
            detail=(
                "当前文章→Slides Prompt 仍要求旧字段 body_points/narration_segments，"
                "与 Step 2A 的精简输出合同不兼容。请载入最新内置模板或升级该自定义模板后再生成。"
            ),
        )
    trace_id = uuid.uuid4().hex[:8]
    raw_plan = run_step2_json_llm(
        project=project,
        system_prompt=compose_step2_system_prompt(prompts["script_system"], prompts["script_output_example"]),
        user_prompt=build_step2_script_user_prompt(
            project_title=project_title,
            article_content=article_content,
            generation_requirement=generation_requirement,
        ),
        artifact_prefix="step2_script_plan",
        schema_hint=script_plan_schema_hint(),
        trace_id=trace_id,
    )
    plan = normalize_slide_script_plan(raw_plan, project_title)
    write_json_atomic(step2_script_plan_path(project), plan)
    write_project_log(project, "step2_script_plan_written", trace_id=trace_id, slide_count=len(plan.get("slides", [])))
    return {"success": True, "script_plan": plan}


def get_step2_script_plan(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    plan = read_plan_json(step2_script_plan_path(project), "尚未生成演讲稿规划")
    return {"success": True, "script_plan": plan}


def update_step2_script_plan(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    article_source = read_project_article_source(project)
    project_title = article_source["title"]
    plan = normalize_slide_script_plan(payload, project_title)
    write_json_atomic(step2_script_plan_path(project), plan)
    return {"success": True, "script_plan": plan}


def execute_step2_visual_plan(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    script_plan = read_plan_json(step2_script_plan_path(project), "请先生成演讲稿规划")
    prompts = read_step2_prompts(project)
    if step2_visual_prompt_uses_legacy_contract(prompts["visual_system"]):
        raise HTTPException(
            status_code=409,
            detail=(
                "当前 Slides→可视化 Prompt 仍依赖旧字段 body_points/narration_segments，"
                "但 Step 2B 现在只接收 slide_id、slide_title 和完整 narration，不接收页面副标题。"
                "请载入最新内置模板或升级该自定义模板后再生成。"
            ),
        )
    trace_id = uuid.uuid4().hex[:8]
    raw_plan = run_step2_json_llm(
        project=project,
        system_prompt=compose_step2_system_prompt(prompts["visual_system"], prompts["visual_output_example"]),
        user_prompt=build_step2_visual_user_prompt(script_plan),
        artifact_prefix="step2_visual_plan",
        schema_hint=visual_plan_schema_hint(),
        trace_id=trace_id,
    )
    plan = normalize_slide_visual_plan(raw_plan, script_plan)
    write_json_atomic(step2_visual_plan_path(project), plan)
    write_project_log(project, "step2_visual_plan_written", trace_id=trace_id, slide_count=len(plan.get("slides", [])))
    return {"success": True, "visual_plan": plan}


def get_step2_visual_plan(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    plan = read_plan_json(step2_visual_plan_path(project), "尚未生成视觉规划")
    return {"success": True, "visual_plan": plan}


def update_step2_visual_plan(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    script_plan = read_plan_json(step2_script_plan_path(project), "请先生成演讲稿规划")
    plan = normalize_slide_visual_plan(payload, script_plan)
    write_json_atomic(step2_visual_plan_path(project), plan)
    return {"success": True, "visual_plan": plan}


def compose_step2_visual_contract(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    article_source = read_project_article_source(project)
    project_title = article_source["title"]
    article_summary = article_source["summary"]
    script_plan = read_plan_json(step2_script_plan_path(project), "请先生成演讲稿规划")
    visual_plan = normalize_slide_visual_plan(
        read_plan_json(step2_visual_plan_path(project), "请先生成视觉规划"),
        script_plan,
    )
    trace_id = uuid.uuid4().hex[:8]
    contract = compose_visual_contract_from_plans(script_plan, visual_plan, project_id, project_title)
    contract = finalize_step2_contract(
        project=project,
        project_id=project_id,
        db=db,
        contract=contract,
        project_title=project_title,
        article_summary=article_summary,
        trace_id=trace_id,
        source="narration_first_compose",
    )
    return {"success": True, "contract": contract}


def get_step2_prompt_preview(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    article_source = read_project_article_source(project)

    storyboard_rules = str((payload or {}).get("rules") or "").strip()
    if not storyboard_rules:
        rules_path = storyboard_rules_path(project)
        if os.path.exists(rules_path):
            with open(rules_path, "r", encoding="utf-8") as f:
                storyboard_rules = f.read().strip()
        else:
            storyboard_rules = default_storyboard_rules()
    profile_text = str((payload or {}).get("profile_yaml") or "").strip()
    profile = (
        parse_storyboard_profile_text(profile_text)
        if profile_text
        else read_project_pipeline_profile(project)
    )
    profile = apply_storyboard_profile_patch(profile, (payload or {}).get("profile_patch"))

    project_title = article_source["title"]
    article_content = article_source["content"]
    article_summary = article_source["summary"]
    system_prompt, user_prompt = build_storyboard_request(
        project_title,
        article_summary,
        article_content,
        storyboard_rules,
        profile,
    )
    return {
        "success": True,
        "system_content": system_prompt,
        "user_content": user_prompt,
    }


def visual_contract_validation_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", "visual_contract.validation.json")


def validate_visual_contract_file(
    project: Project,
    contract_path: str,
    *,
    source: str,
    trace_id: str = "",
) -> Dict[str, Any]:
    validate_script = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "validate_visual_contract.py"))
    validation_args = [sys.executable, validate_script, "--contract", contract_path]
    project_profile_path = storyboard_profile_path(project)
    if os.path.exists(project_profile_path):
        validation_args.extend(["--profile", project_profile_path])
    result = subprocess.run(
        validation_args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    contract_bytes = Path(contract_path).read_bytes()
    validation = {
        "valid": result.returncode == 0,
        "contract_sha256": hashlib.sha256(contract_bytes).hexdigest(),
        "validated_at": datetime.now().isoformat(timespec="seconds"),
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "source": source,
        "trace_id": trace_id,
    }
    write_json_atomic(visual_contract_validation_path(project), validation)
    return validation


def storyboard_validation_gate_enabled(project: Project) -> bool:
    profile = read_project_pipeline_profile(project)
    gates = profile.get("quality_gates") if isinstance(profile.get("quality_gates"), dict) else {}
    return bool(gates.get("pause_on_storyboard_validation_error", True))


def finalize_step2_contract(
    *,
    project: Project,
    project_id: str,
    db: Session,
    contract: Dict[str, Any],
    project_title: str,
    article_summary: str,
    trace_id: str,
    source: str,
) -> Dict[str, Any]:
    contract["version"] = "visual_contract_v1"
    if "topic" not in contract or not isinstance(contract.get("topic"), dict):
        contract["topic"] = {
            "topic_id": "topic_" + project_id,
            "topic_name": project_title,
            "topic_summary": article_summary,
        }
    contract = normalize_visual_contract(contract, read_project_pipeline_profile(project))

    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    os.makedirs(os.path.dirname(contract_path), exist_ok=True)
    contract["version"] = "visual_contract_v1"
    contract["topic"] = {
        "topic_id": "topic_" + project_id,
        "topic_name": project_title,
        "topic_summary": article_summary,
    }
    with open(contract_path, "w", encoding="utf-8") as f:
        json.dump(contract, f, ensure_ascii=False, indent=2)
    write_project_log(
        project,
        "step2_contract_written",
        trace_id=trace_id,
        contract_path=contract_path,
        slide_count=len(contract.get("slides", [])) if isinstance(contract.get("slides"), list) else 0,
        source=source,
    )

    validation = validate_visual_contract_file(
        project,
        contract_path,
        source=source,
        trace_id=trace_id,
    )

    if not validation["valid"]:
        logger.warning("Visual contract validation warning:\n%s", validation["stderr"])
        write_project_log(
            project,
            "step2_contract_validation_warning",
            trace_id=trace_id,
            returncode=validation["returncode"],
            stderr=validation["stderr"],
            source=source,
        )
        if storyboard_validation_gate_enabled(project):
            mark_step_retry_needed(project, 2, db)
            raise HTTPException(
                status_code=422,
                detail="分镜合同校验失败，质量门已暂停流程：" + (validation["stderr"] or "请检查分镜结构"),
            )
    else:
        write_project_log(
            project,
            "step2_contract_validation_success",
            trace_id=trace_id,
            stdout=validation["stdout"],
            source=source,
        )

    handle_step_navigation(project, 2, db)
    write_project_log(project, "step2_execute_completed", trace_id=trace_id, source=source)
    return contract


def build_step2_scaffold_contract(
    *,
    project: Project,
    project_title: str,
    article_content: str,
    trace_id: str,
) -> Dict[str, Any]:
    profile = read_project_pipeline_profile(project)
    slide_count_text, _ = storyboard_requirements(article_content, profile)
    min_slides, max_slides = parse_range_text(slide_count_text, 4, 8)
    fallback_path = os.path.join(project.run_dir, "planning", f"visual_contract_fallback_{trace_id}.json")
    if os.path.exists(fallback_path):
        os.remove(fallback_path)

    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "scripts", "write_visual_contract.py"))
    args = [
        sys.executable,
        script_path,
        "--run-dir",
        project.run_dir,
        "--out",
        fallback_path,
        "--topic-name",
        project_title,
        "--min-slides",
        str(min_slides),
        "--max-slides",
        str(max_slides),
        "--subtitle-policy",
        "no_slides_have_subtitle",
        "--overwrite",
    ]
    write_project_log(
        project,
        "step2_scaffold_fallback_start",
        trace_id=trace_id,
        min_slides=min_slides,
        max_slides=max_slides,
        subtitle_policy="no_slides_have_subtitle",
    )
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    if result.returncode != 0 or not os.path.exists(fallback_path):
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Step2 scaffold fallback failed")
    with open(fallback_path, "r", encoding="utf-8") as f:
        contract = json.load(f)
    write_project_log(
        project,
        "step2_scaffold_fallback_generated",
        trace_id=trace_id,
        contract_path=fallback_path,
        stdout=result.stdout.strip(),
    )
    return contract


def execute_step2(
    project_id: str,
    payload: Optional[Dict[str, Any]] = None,
    db: Session = Depends(get_db),
):
    """Compatibility endpoint delegated to the narration-first Step 2 pipeline."""

    execute_step2_script_plan(project_id, payload if isinstance(payload, dict) else {}, db)
    execute_step2_visual_plan(project_id, db)
    result = compose_step2_visual_contract(project_id, db)
    return {
        **result,
        "deprecated_route": True,
        "preferred_routes": [
            f"/api/projects/{project_id}/steps/2/script/execute",
            f"/api/projects/{project_id}/steps/2/visual/execute",
            f"/api/projects/{project_id}/steps/2/compose",
        ],
    }


def get_step2_result(project_id: str, db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        return {"success": False, "message": "尚未生成分镜规划"}
        
    with open(contract_path, "r", encoding="utf-8") as f:
        stored_contract = json.load(f)
    contract = normalize_visual_contract(stored_contract, read_project_pipeline_profile(project))
    migration_required = json.dumps(contract, ensure_ascii=False, sort_keys=True) != json.dumps(
        stored_contract,
        ensure_ascii=False,
        sort_keys=True,
    )
    return {
        "success": True,
        "contract": contract,
        "repair": {
            "required": migration_required,
            "reasons": ["visual_contract_schema_normalization"] if migration_required else [],
            "endpoint": f"/api/projects/{project_id}/steps/2/repair",
        },
    }


def repair_step2_result(project_id: str, db: Session = Depends(get_db)):
    """Persist schema normalization explicitly instead of mutating on GET."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="尚未生成分镜规划")
    stored_contract = read_json_file(contract_path, {})
    contract = normalize_visual_contract(stored_contract, read_project_pipeline_profile(project))
    changed = json.dumps(contract, ensure_ascii=False, sort_keys=True) != json.dumps(
        stored_contract,
        ensure_ascii=False,
        sort_keys=True,
    )
    if changed:
        write_json_atomic(contract_path, contract)
        current_slide_ids = contract_slide_ids_from_payload(contract)
        sync_reveal_manifest_to_contract(project, current_slide_ids)
        sync_narration_beats_to_contract(project, current_slide_ids)
        validate_visual_contract_file(project, contract_path, source="explicit_schema_repair")
        invalidate_after_upstream_edit(project, 2, db)
    return {"success": True, "changed": changed, "contract": contract}

def update_step2_result(project_id: str, payload: Dict[str, Any], db: Session = Depends(get_db)):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
        
    payload = normalize_visual_contract(payload, read_project_pipeline_profile(project))
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    existing_contract = read_json_file(contract_path, {})
    previous_slide_ids = contract_slide_ids_from_payload(existing_contract)
    changed = json.dumps(existing_contract, ensure_ascii=False, sort_keys=True) != json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
    )
    if not changed:
        return {
            "success": True,
            "contract": payload,
            "validation": read_json_file(visual_contract_validation_path(project), {}),
            "changed": False,
        }
    with open(contract_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    current_slide_ids = contract_slide_ids_from_payload(payload)
    removed_slide_ids = [slide_id for slide_id in previous_slide_ids if slide_id not in current_slide_ids]
    for slide_id in removed_slide_ids:
        slide_path = Path(storage_slide_file(project.run_dir, slide_id, "visual_draft.png")).parent
        if slide_path.exists():
            shutil.rmtree(slide_path)

    if not current_slide_ids:
        validation = {
            "valid": False,
            "editable_empty": True,
            "contract_sha256": hashlib.sha256(Path(contract_path).read_bytes()).hexdigest(),
            "validated_at": datetime.now().isoformat(timespec="seconds"),
            "returncode": 0,
            "stdout": "",
            "stderr": "分镜列表为空；可以继续添加分镜，但不能进入图片生成。",
            "source": "manual_empty_storyboard",
            "trace_id": "",
        }
        write_json_atomic(visual_contract_validation_path(project), validation)
        sync_reveal_manifest_to_contract(project, [])
        sync_narration_beats_to_contract(project, [])
        sync_narration_sources_from_contract(project, existing_contract, payload)
        invalidation_service.empty_storyboard_changed(project)
        db.commit()
        payload = read_json_file(contract_path, payload)
        return {"success": True, "contract": payload, "validation": validation, "changed": True}

    validation = validate_visual_contract_file(project, contract_path, source="manual_autosave")
    if validation.get("valid"):
        sync_reveal_manifest_to_contract(project, current_slide_ids)
        sync_narration_beats_to_contract(project, current_slide_ids)
        sync_narration_sources_from_contract(project, existing_contract, payload)
        payload = read_json_file(contract_path, payload)
    invalidate_after_upstream_edit(project, 2, db)

    return {"success": True, "contract": payload, "validation": validation, "changed": True}


class ManualSkeletonSlide(BaseModel):
    slide_id: Optional[str] = None
    main_title: str
    narration: str


class ManualSkeletonPayload(BaseModel):
    slides: List[ManualSkeletonSlide]


def submit_step2_manual_skeleton(
    project_id: str,
    payload: ManualSkeletonPayload,
    db: Session = Depends(get_db),
):
    """Manual mode: build a visual_contract.json from title + narration only.

    Each slide produces an empty visual_groups[] (full-slide static render)
    and one narration_beat entry bound to the spoken text. AI Mask is not
    triggered; the user can still click "运行 AI 标注" later if desired.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not payload.slides:
        raise HTTPException(status_code=400, detail="slides 不能为空")

    article_source = read_project_article_source(project, required=False)
    project_title = article_source.get("title") or project.name or project_id
    article_summary = article_source.get("summary", "")

    contract_slides: List[Dict[str, Any]] = []
    for index, slide in enumerate(payload.slides, start=1):
        slide_id = (slide.slide_id or f"slide_{index:03d}").strip()
        main_title = (slide.main_title or "").strip()
        narration = (slide.narration or "").strip()
        if not main_title:
            raise HTTPException(status_code=400, detail=f"{slide_id} 标题不能为空")
        if not narration:
            raise HTTPException(status_code=400, detail=f"{slide_id} 演讲稿不能为空")
        contract_slides.append({
            "slide_id": slide_id,
            "main_title": main_title,
            "subtitle": "",
            "core_message": narration,
            "body_content": [narration],
            "visual_groups": [],
            "narration_beats": [
                {
                    "id": f"{slide_id}_beat_001",
                    "group_id": None,
                    "visible_anchor": "",
                    "spoken_intent": main_title,
                    "spoken_text": narration,
                    "content_unit_id": f"{slide_id}_unit_001",
                }
            ],
        })

    previous_contract = read_json_file(
        os.path.join(project.run_dir, "planning", "visual_contract.json"),
        {},
    )
    contract = {
        "version": "visual_contract_v1",
        "presentation_policy": {
            "subtitle_policy": "no_slides_have_subtitle",
            "subtitle_decided_by": "system_no_subtitle_contract",
            "visual_narration_mapping": "manual_free_v1",
        },
        "topic": {
            "topic_id": "topic_" + project_id,
            "topic_name": project_title,
            "topic_summary": article_summary,
        },
        "slides": contract_slides,
    }

    trace_id = uuid.uuid4().hex[:8]
    contract = finalize_step2_contract(
        project=project,
        project_id=project_id,
        db=db,
        contract=contract,
        project_title=project_title,
        article_summary=article_summary,
        trace_id=trace_id,
        source="manual_skeleton_submit",
    )
    sync_narration_sources_from_contract(project, previous_contract, contract)
    # Ensure the project reflects manual mode so the frontend can render the
    # correct UI affordances (e.g., hide auto-trigger AI Mask).
    if project.ai_mode != "manual":
        project.ai_mode = "manual"
        db.commit()
        db.refresh(project)
    return {"success": True, "contract": contract, "ai_mode": project.ai_mode}


# ==================== 步骤 3-4: 图片生成与管理 ====================



