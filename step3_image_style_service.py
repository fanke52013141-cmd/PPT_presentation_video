"""Step 3 image-style state service.

New image style state belongs to Step 3 and is stored in
``planning/step3_image_style.json``. Legacy Project Profile image style is still
used as fallback for old projects.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


STATE_FILENAME = "step3_image_style.json"


def _run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def _state_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / STATE_FILENAME


def _profile_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / "project_profile.json"


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return deepcopy(fallback)
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return deepcopy(fallback)
    return value if isinstance(value, dict) else deepcopy(fallback)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_text(value: Any, limit: int = 8000) -> str:
    return str(value or "").strip()[:limit]


def _step3_style_state(project: Any) -> dict[str, Any]:
    state = _read_json(_state_path(project), {})
    return state if isinstance(state, dict) else {}


def _step3_style(project: Any) -> dict[str, Any]:
    state = _step3_style_state(project)
    if isinstance(state.get("image_style_profile"), dict):
        return state["image_style_profile"]
    legacy = _read_json(_profile_path(project), {}).get("image_style_profile")
    return legacy if isinstance(legacy, dict) else {}


def _save_step3_style(project: Any, style: dict[str, Any], source: str) -> dict[str, Any]:
    existing = _step3_style_state(project)
    state = {
        "version": "step3_image_style_v1",
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "image_style_profile": style if isinstance(style, dict) else {},
        "reference_images": existing.get("reference_images", []) if isinstance(existing.get("reference_images"), list) else [],
        "note": "Step 3 owns image style. Project creation does not set image style.",
    }
    _write_json(_state_path(project), state)
    return state


def _manual_style_from_payload(payload: Any, current: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("style") if isinstance(payload, dict) and isinstance(payload.get("style"), dict) else payload
    if not isinstance(source, dict):
        source = {}
    current = current if isinstance(current, dict) else {}
    system_content = _safe_text(source.get("system_content") or current.get("system_content"), 12000)
    style = {
        **current,
        **source,
        "source": _safe_text(source.get("source") or current.get("source") or "manual_system_content", 80),
        "style_name": _safe_text(source.get("style_name") or current.get("style_name") or "手动 System Content", 120),
        "style_summary": _safe_text(source.get("style_summary") or current.get("style_summary") or "由用户在 Step 3 图片风格面板手动维护。", 1000),
        "system_content": system_content,
        "reference_image_count_target": 3,
    }
    prompts = source.get("sample_reference_image_prompts")
    if isinstance(prompts, list):
        style["sample_reference_image_prompts"] = [_safe_text(item, 4000) for item in prompts if _safe_text(item, 4000)][:3]
    else:
        # Reference scenes are content-neutral examples, not copies of the full
        # style System Content.  The generator supplies three safe defaults.
        style["sample_reference_image_prompts"] = []
    return style


def _save_reference_images_to_step3_state(project: Any, manifest: dict[str, Any]) -> None:
    state = _step3_style_state(project)
    if not state:
        state = {
            "version": "step3_image_style_v1",
            "source": "reference_images",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "image_style_profile": _step3_style(project),
            "note": "Step 3 owns image style. Project creation does not set image style.",
        }
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    state["reference_images"] = manifest.get("images", []) if isinstance(manifest, dict) else []
    _write_json(_state_path(project), state)


def manual_style_from_payload(*args: Any, **kwargs: Any) -> Any:
    """公开包装（审查 L-06）：路由与服务经公开名调用。"""
    return _manual_style_from_payload(*args, **kwargs)

def safe_text(*args: Any, **kwargs: Any) -> Any:
    """公开包装（审查 L-06）：路由与服务经公开名调用。"""
    return _safe_text(*args, **kwargs)

def save_step3_style(*args: Any, **kwargs: Any) -> Any:
    """公开包装（审查 L-06）：路由与服务经公开名调用。"""
    return _save_step3_style(*args, **kwargs)

def state_path(*args: Any, **kwargs: Any) -> Any:
    """公开包装（审查 L-06）：路由与服务经公开名调用。"""
    return _state_path(*args, **kwargs)

def step3_style(*args: Any, **kwargs: Any) -> Any:
    """公开包装（审查 L-06）：路由与服务经公开名调用。"""
    return _step3_style(*args, **kwargs)

def step3_style_state(*args: Any, **kwargs: Any) -> Any:
    """公开包装（审查 L-06）：路由与服务经公开名调用。"""
    return _step3_style_state(*args, **kwargs)
