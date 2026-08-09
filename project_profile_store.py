"""Lightweight Project Profile storage and normalization.

Project creation does not inject storyboard or image-style defaults. Only
explicit lightweight fields are saved while existing optional style fields are
preserved for old projects and Step 3.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from pipeline_lifecycle import write_json_atomic

PROFILE_VERSION = "project_profile_v1"
PROFILE_FILENAME = "project_profile.json"

DEFAULT_QUALITY_GATES = {
    "pause_on_storyboard_validation_error": True,
    "pause_on_image_generation_failure": True,
    "pause_on_ai_mask_low_confidence": True,
    "pause_on_tts_failure": True,
    "pause_on_render_failure": True,
}


def _run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def _profile_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / PROFILE_FILENAME


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return deepcopy(fallback)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return deepcopy(fallback)
    return value if isinstance(value, dict) else deepcopy(fallback)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    write_json_atomic(path, value)


def _safe_text(value: Any, limit: int = 2000) -> str:
    return str(value or "").strip()[:limit]


def _safe_dict(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _normalize_quality_gates(value: Any, *, strict: bool = False) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    normalized: dict[str, bool] = {}
    for key, default in DEFAULT_QUALITY_GATES.items():
        raw = source.get(key, default)
        if isinstance(raw, bool):
            normalized[key] = raw
            continue
        if strict:
            raise ValueError(f"quality_gates.{key} 必须是布尔值")
        if isinstance(raw, str) and raw.strip().lower() in {"true", "false"}:
            normalized[key] = raw.strip().lower() == "true"
        elif isinstance(raw, int) and raw in (0, 1):
            normalized[key] = bool(raw)
        else:
            normalized[key] = default
    return normalized


def _normalize_lightweight_profile(
    payload: Any,
    existing: dict[str, Any] | None = None,
    *,
    strict: bool = False,
) -> dict[str, Any]:
    source = payload.get("profile") if isinstance(payload, dict) and isinstance(payload.get("profile"), dict) else payload
    if not isinstance(source, dict):
        source = {}
    existing = existing if isinstance(existing, dict) else {}

    automation_mode = _safe_text(source.get("automation_mode") or existing.get("automation_mode") or "manual_review", 40)
    profile: dict[str, Any] = {
        "version": PROFILE_VERSION,
        "automation_mode": "auto" if automation_mode == "auto" else "manual_review",
        "quality_gates": _normalize_quality_gates(
            source.get("quality_gates") if "quality_gates" in source else existing.get("quality_gates"),
            strict=strict,
        ),
        "last_used_storyboard_template_id": _safe_text(source.get("last_used_storyboard_template_id") or existing.get("last_used_storyboard_template_id"), 120),
        "last_used_image_style_template_id": _safe_text(source.get("last_used_image_style_template_id") or existing.get("last_used_image_style_template_id"), 120),
        "notes": _safe_text(source.get("notes") or existing.get("notes") or "Lightweight profile only. Step 2 owns storyboard style; Step 3 owns image style and references.", 1000),
    }

    # Preserve optional legacy or Step-3-authored fields only when explicitly
    # provided or already present. Do not synthesize defaults here.
    for key in ("storyboard_profile", "image_style_profile", "background_profile"):
        if isinstance(source.get(key), dict):
            profile[key] = _safe_dict(source.get(key))
        elif isinstance(existing.get(key), dict):
            profile[key] = _safe_dict(existing.get(key))

    return profile


def _canonical_mode(project: Any, fallback: str) -> str:
    value = _safe_text(getattr(project, "ai_mode", ""), 40).lower()
    if value in {"auto", "manual"}:
        return "auto" if value == "auto" else "manual_review"
    return "auto" if fallback == "auto" else "manual_review"


def load_profile(project: Any) -> dict[str, Any]:
    profile = _normalize_lightweight_profile(_read_json(_profile_path(project), {}), {})
    profile["automation_mode"] = _canonical_mode(project, profile["automation_mode"])
    return profile


def save_profile(project: Any, payload: Any) -> dict[str, Any]:
    existing = _read_json(_profile_path(project), {})
    profile = _normalize_lightweight_profile(payload, existing, strict=True)
    profile["automation_mode"] = _canonical_mode(project, profile["automation_mode"])
    _write_json(_profile_path(project), profile)
    return profile


