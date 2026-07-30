"""Persistence helpers for named Step 3 image-style templates."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import time
from typing import Any


STATE_FILENAME = "step3_image_style.json"
BUILTIN_HANDDRAWN_TEMPLATE_ID = "handdrawn"
BUILTIN_HANDDRAWN_TEMPLATE_NAME = "手绘风格"


def _run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def _step3_state_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / STATE_FILENAME


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback
    return value if isinstance(value, dict) else fallback


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _save_step3_style_state(
    project: Any,
    style: dict[str, Any],
    source: str,
) -> dict[str, Any]:
    existing = _read_json(_step3_state_path(project), {})
    state = {
        "version": "step3_image_style_v1",
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "image_style_profile": style if isinstance(style, dict) else {},
        "reference_images": (
            existing.get("reference_images", [])
            if isinstance(existing.get("reference_images"), list)
            else []
        ),
        "note": "Step 3 owns image style. Project creation does not set image style.",
    }
    _write_json(_step3_state_path(project), state)
    return state


def _rewrite_reference_urls(value: Any, project_id: str) -> Any:
    if isinstance(value, dict):
        result = {
            key: _rewrite_reference_urls(item, project_id)
            for key, item in value.items()
        }
        if "index" in result and isinstance(result.get("url"), str):
            try:
                index = int(result["index"])
                result["url"] = (
                    f"/api/projects/{project_id}/steps/3/image-style/"
                    f"reference-images/{index}?t={int(time.time())}"
                )
            except Exception:
                pass
        return result
    if isinstance(value, list):
        return [_rewrite_reference_urls(item, project_id) for item in value]
    return value
