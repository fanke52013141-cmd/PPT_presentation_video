#!/usr/bin/env python3
"""Shared helpers for configurable storyboard, image prompt, reveal and TTS profiles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE_PATH = REPO_ROOT / "config" / "pipeline_profiles.yaml"
DEFAULT_INVARIANTS_PATH = REPO_ROOT / "config" / "production_invariants.yaml"

REVEAL_ACTION_ALIASES = {
    "cover_wipe_left_to_right": "cover_wipe_left_to_right",
    "cover_wipe_right_to_left": "cover_wipe_right_to_left",
    "cover_wipe_top_to_bottom": "cover_wipe_top_to_bottom",
    "cover_wipe_bottom_to_top": "cover_wipe_bottom_to_top",
    "wipe_left_to_right": "wipe_left_to_right",
    "wipe_right_to_left": "wipe_right_to_left",
    "wipe_top_to_bottom": "wipe_top_to_bottom",
    "wipe_bottom_to_top": "wipe_bottom_to_top",
    "soft_zoom_in": "crop_soft_zoom_in",
    "fade_in": "crop_fade_up",
    "fade_up": "crop_fade_up",
    "slide_in_left": "crop_slide_in_left",
}


def read_pipeline_profile(path: Path | None = None) -> dict[str, Any]:
    profile_path = path or DEFAULT_PROFILE_PATH
    payload = yaml.safe_load(profile_path.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Pipeline profile must be a YAML object: {profile_path}")
    return payload


def read_production_invariants(path: Path | None = None) -> dict[str, Any]:
    invariants_path = path or DEFAULT_INVARIANTS_PATH
    payload = yaml.safe_load(invariants_path.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Production invariants must be a YAML object: {invariants_path}")
    return payload


def _nested_dict(payload: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key)
    return current if isinstance(current, dict) else {}


def _nested_list(payload: dict[str, Any], *keys: str) -> list[Any]:
    current: Any = payload
    for key in keys:
        if not isinstance(current, dict):
            return []
        current = current.get(key)
    return current if isinstance(current, list) else []


def article_size_key(article_content: str) -> str:
    article_chars = len("".join(str(article_content or "").split()))
    if article_chars <= 1200:
        return "short_article"
    if article_chars <= 3000:
        return "medium_article"
    return "long_article"


def storyboard_requirements(article_content: str, profile: dict[str, Any]) -> tuple[str, str]:
    size_key = article_size_key(article_content)
    storyboard = _nested_dict(profile, "storyboard")
    slide_count = _nested_dict(storyboard, "slide_count").get(size_key)
    anchor_count = _nested_dict(storyboard, "visual_anchor_count").get(size_key)
    if anchor_count is None:
        anchor_count = _nested_dict(storyboard, "visual_group_count").get(size_key)
    return str(slide_count or "4-8"), str(anchor_count or "2-5")


def role_catalog(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    roles = _nested_dict(profile, "storyboard", "roles")
    return {
        str(key): value
        for key, value in roles.items()
        if isinstance(value, dict) and value.get("enabled") is not False
    }


def storyboard_profile_prompt(article_content: str, profile: dict[str, Any]) -> str:
    slide_count, anchor_count = storyboard_requirements(article_content, profile)
    roles = role_catalog(profile)
    role_lines: list[str] = []
    for role, cfg in roles.items():
        label = str(cfg.get("label") or role)
        description = str(cfg.get("description") or "").strip()
        role_lines.append(f"- {role}（{label}）：{description}")
    structure_rules = [
        f"- {str(item).strip()}"
        for item in _nested_list(profile, "storyboard", "structure_rules")
        if str(item).strip()
    ]
    presentation_rules = [
        f"- {str(item).strip()}"
        for item in _nested_list(profile, "storyboard", "presentation_policy_rules")
        if str(item).strip()
    ]
    required_fields = ", ".join(str(item) for item in _nested_list(profile, "storyboard", "required_slide_fields"))
    optional_fields = ", ".join(str(item) for item in _nested_list(profile, "storyboard", "optional_slide_fields"))
    return "\n".join(
        [
            "可配置分镜结构要求：",
            f"- 根据文章长度，本次建议生成 {slide_count} 页 Slide。",
            f"- 每页建议仅给出 {anchor_count} 个后置视觉锚点；锚点只服务 Mask/Reveal，不是前置版式模板。",
            "- 分镜以演讲稿和正文内容为中心，不要在分镜阶段拆成图示、数据、总结、流程等固定 role。",
            "- 先在顶层输出 presentation_policy；副标题必须由 AI 做项目级一次性决策，不能逐页随机。",
            "- presentation_policy.subtitle_policy 只能是 all_slides_have_subtitle 或 no_slides_have_subtitle。",
            f"- Slide 固定结构字段：{required_fields or 'slide_id, main_title, narration'}。",
            f"- Slide 扩展结构字段：{optional_fields or 'subtitle, core_message, body_content, visual_intent, visual_groups, narration_beats'}。",
            "- 最小 role 集合：",
            *role_lines,
            "- presentation_policy 规则：",
            *presentation_rules,
            "- 结构规则：",
            *structure_rules,
        ]
    )


def image_prompt_profile_text(profile: dict[str, Any]) -> str:
    image_prompt = _nested_dict(profile, "image_prompt")
    opening = str(image_prompt.get("opening") or "").strip()
    invariant_rules = [
        f"- {str(item).strip()}"
        for item in _nested_list(profile, "image_prompt", "invariant_rules")
        if str(item).strip()
    ]
    creative_rules = [
        f"- {str(item).strip()}"
        for item in _nested_list(profile, "image_prompt", "creative_rules")
        if str(item).strip()
    ]
    lines = []
    if opening:
        lines.append(opening)
    if invariant_rules:
        lines.append("通用生产铁律（不可被风格覆盖）：")
        lines.extend(invariant_rules)
    if creative_rules:
        lines.append("可泛化创意指导（可随内容和风格变化）：")
        lines.extend(creative_rules)
    return "\n".join(lines)


def allowed_reveal_actions(profile: dict[str, Any] | None = None) -> set[str]:
    if profile is None:
        profile = read_pipeline_profile()
    configured = {
        str(item).strip()
        for item in _nested_list(profile, "reveal", "allowed_actions")
        if str(item).strip()
    }
    configured.update(
        {
            "cover_fade_out",
            "cover_wipe_left_to_right",
            "cover_wipe_right_to_left",
            "cover_wipe_top_to_bottom",
            "cover_wipe_bottom_to_top",
            "fog_diagonal_erase",
            "crop_fade_up",
            "crop_slide_in_left",
            "crop_soft_zoom_in",
            "highlight",
        }
    )
    return configured


def normalize_reveal_action(action: str, profile: dict[str, Any] | None = None, for_renderer: bool = False) -> str:
    action = str(action or "").strip() or "crop_fade_up"
    if for_renderer:
        return REVEAL_ACTION_ALIASES.get(action, action)
    if profile is not None and action not in allowed_reveal_actions(profile):
        return REVEAL_ACTION_ALIASES.get(action, "crop_fade_up")
    return action


def default_reveal_for_role(role: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    if profile is None:
        profile = read_pipeline_profile()
    role = str(role or "body_content").strip()
    defaults = _nested_dict(profile, "reveal", "default_by_role")
    reveal = defaults.get(role)
    if not isinstance(reveal, dict):
        reveal = defaults.get("body_content") or defaults.get("content_body")
    if not isinstance(reveal, dict):
        reveal = {"type": "crop_fade_up", "duration": 0.75}
    result = dict(reveal)
    result["type"] = normalize_reveal_action(str(result.get("type") or "crop_fade_up"), profile)
    return result
