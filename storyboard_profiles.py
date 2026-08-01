"""Storyboard profile parsing, editing, and built-in rule sources."""

from __future__ import annotations

import copy
import os
from typing import Any, Dict

from fastapi import HTTPException
import yaml

from database import Project
from repository_paths import HANDDRAWN_STORYBOARD_RULES_PATH, REPO_ROOT
from scripts.pipeline_profiles import read_pipeline_profile


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


