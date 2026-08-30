"""Canonical project canvas profiles.

Canvas geometry is project data, not a renderer-only option.  Keeping the
profiles here gives every pipeline stage the same dimensions while retaining
the landscape defaults used by existing projects.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from pipeline_lifecycle import write_json_atomic


DEFAULT_CANVAS_PROFILE = "landscape_16_9"

CANVAS_PROFILES: dict[str, dict[str, Any]] = {
    "landscape_16_9": {
        "id": "landscape_16_9",
        "orientation": "landscape",
        "aspect_ratio": "16:9",
        "width": 1920,
        "height": 1080,
        "subtitle_safe_zone": {"top": 930, "bottom": 1080},
        "content_safe_area": {"left": 80, "top": 235, "right": 1840, "bottom": 930},
    },
    "portrait_9_16": {
        "id": "portrait_9_16",
        "orientation": "portrait",
        "aspect_ratio": "9:16",
        "width": 1080,
        "height": 1920,
        "subtitle_safe_zone": {"top": 1650, "bottom": 1920},
        "content_safe_area": {"left": 64, "top": 180, "right": 1016, "bottom": 1650},
    },
}


def normalize_canvas_profile(value: Any) -> str:
    """Return a supported profile id, falling back for old callers/data."""
    candidate = str(value or DEFAULT_CANVAS_PROFILE).strip().lower()
    aliases = {
        "landscape": "landscape_16_9",
        "16:9": "landscape_16_9",
        "16/9": "landscape_16_9",
        "portrait": "portrait_9_16",
        "9:16": "portrait_9_16",
        "9/16": "portrait_9_16",
    }
    candidate = aliases.get(candidate, candidate)
    return candidate if candidate in CANVAS_PROFILES else DEFAULT_CANVAS_PROFILE


def get_canvas_profile(value: Any = None) -> dict[str, Any]:
    """Return a defensive copy of a canonical canvas profile."""
    return deepcopy(CANVAS_PROFILES[normalize_canvas_profile(value)])


def get_project_canvas(project: Any) -> dict[str, Any]:
    return get_canvas_profile(getattr(project, "canvas_profile", None))


def canvas_profile_path(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve() / "planning" / "canvas_profile.json"


def write_project_canvas_snapshot(project: Any) -> dict[str, Any]:
    """Persist the resolved profile so a run remains reproducible."""
    profile = get_project_canvas(project)
    payload = {"version": "canvas_profile_v1", **profile}
    path = canvas_profile_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, payload)
    return payload


def read_project_canvas_snapshot(project: Any) -> dict[str, Any]:
    path = canvas_profile_path(project)
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return get_project_canvas(project)
    if not isinstance(payload, dict):
        return get_project_canvas(project)
    return get_canvas_profile(payload.get("id") or getattr(project, "canvas_profile", None))


def canvas_prompt_context(project_or_profile: Any) -> dict[str, Any]:
    profile = (
        get_project_canvas(project_or_profile)
        if hasattr(project_or_profile, "run_dir")
        else get_canvas_profile(project_or_profile)
    )
    safe_zone = profile["subtitle_safe_zone"]
    return {
        "profile": profile["id"],
        "orientation": profile["orientation"],
        "aspect_ratio": profile["aspect_ratio"],
        "width": profile["width"],
        "height": profile["height"],
        "subtitle_safe_top": safe_zone["top"],
        "subtitle_safe_bottom": safe_zone["bottom"],
    }


def canvas_prompt_instructions(project_or_profile: Any) -> str:
    """Return only profile-specific prompt rules.

    Landscape returns an empty string so legacy prompts remain compatible.
    Portrait gets explicit layout and subtitle-safe-area rules.
    """
    context = canvas_prompt_context(project_or_profile)
    if context["orientation"] != "portrait":
        return ""
    return (
        "=== 竖屏画布构图规则 ===\n"
        f"当前画布为 {context['aspect_ratio']} 竖屏短视频画布，尺寸为 "
        f"{context['width']}×{context['height']}。\n"
        "优先使用上下或单列构图，不使用需要横向展开的宽表格和复杂多列布局；"
        "主体集中在画布中央，左右边缘保留安全边距。\n"
        f"底部 y={context['subtitle_safe_top']}..{context['subtitle_safe_bottom']} "
        "为视频字幕安全区，禁止放置标题、正文、图标、箭头、人物或装饰。\n"
        "标题保持简短，正文减少为 3-5 条短句，保证手机端可读且各语义元素清晰分离。"
    )
