"""Distinguish inherited package subtitle defaults from explicit project edits."""
from __future__ import annotations

import json
from typing import Any


def inherited_subtitle_override(project: Any, settings: dict[str, Any]) -> dict[str, Any]:
    style = settings.get("subtitle_style")
    if not isinstance(style, dict):
        return {}
    source = settings.get("subtitle_style_source")
    if source == "project":
        return style
    if source == "package":
        return {}
    from project_config_runtime import project_config_path
    path = project_config_path(project)
    original = {}
    if path is not None:
        try:
            snapshot = json.loads(path.read_text(encoding="utf-8-sig"))
            payload = snapshot.get("payload", {}) if isinstance(snapshot, dict) else {}
            if isinstance(payload, dict) and isinstance(payload.get("schema_version"), str):
                original = payload.get("subtitle", {})
        except (OSError, ValueError, UnicodeDecodeError):
            pass
    if not isinstance(original, dict):
        original = {}
    # Creation used to copy the entire package style without provenance.
    # Preserve edits differing from that original value; inherit unchanged keys.
    return {key: value for key, value in style.items() if key not in original or value != original[key]}
