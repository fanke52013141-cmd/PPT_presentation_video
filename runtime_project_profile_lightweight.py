"""Lightweight Project Profile route override.

Project creation should not inject storyboard or image-style defaults. Those are
owned by Step 2 and Step 3. This override is inserted before the legacy Project
Profile routes and saves only the fields explicitly provided by the lightweight
create flow, while preserving existing optional style fields for older projects
or Step 3 image-style tools.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from copy import deepcopy
from pathlib import Path
from types import ModuleType
from typing import Any

try:
    import runtime_ai_mask_semantic_patch  # noqa: F401
except Exception:
    pass

PATCH_MARKER = "__ppt_project_profile_lightweight_patch__"
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _safe_text(value: Any, limit: int = 2000) -> str:
    return str(value or "").strip()[:limit]


def _safe_dict(value: Any) -> dict[str, Any]:
    return deepcopy(value) if isinstance(value, dict) else {}


def _normalize_quality_gates(value: Any) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    return {key: bool(source.get(key, default)) for key, default in DEFAULT_QUALITY_GATES.items()}


def _normalize_lightweight_profile(payload: Any, existing: dict[str, Any] | None = None) -> dict[str, Any]:
    source = payload.get("profile") if isinstance(payload, dict) and isinstance(payload.get("profile"), dict) else payload
    if not isinstance(source, dict):
        source = {}
    existing = existing if isinstance(existing, dict) else {}

    automation_mode = _safe_text(source.get("automation_mode") or existing.get("automation_mode") or "manual_review", 40)
    profile: dict[str, Any] = {
        "version": PROFILE_VERSION,
        "automation_mode": "auto" if automation_mode == "auto" else "manual_review",
        "quality_gates": _normalize_quality_gates(source.get("quality_gates") if "quality_gates" in source else existing.get("quality_gates")),
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


def _project_or_404(server_module: ModuleType, db: Any, project_id: str) -> Any:
    project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
    if not project:
        raise server_module.HTTPException(status_code=404, detail="项目不存在")
    return project


def _route_methods(route: Any) -> set[str]:
    return set(getattr(route, "methods", []) or [])


def _insert_before_existing(app: Any, path: str, methods: set[str], route: Any) -> None:
    routes = getattr(getattr(app, "router", None), "routes", None)
    if not isinstance(routes, list):
        app.add_api_route(path, route.endpoint, methods=list(methods))
        return
    for index, existing in enumerate(routes):
        if str(getattr(existing, "path", "")) == path and methods.intersection(_route_methods(existing)):
            routes.insert(index, route)
            return
    routes.append(route)


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db")
    if not all(hasattr(server_module, name) for name in required):
        return False

    from fastapi.routing import APIRoute

    app = server_module.app

    def get_profile(project_id: str, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        profile = _normalize_lightweight_profile(_read_json(_profile_path(project), {}), {})
        return {"success": True, "profile": profile}

    def save_profile(project_id: str, payload: dict[str, Any], db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        existing = _read_json(_profile_path(project), {})
        profile = _normalize_lightweight_profile(payload if isinstance(payload, dict) else {}, existing)
        _write_json(_profile_path(project), profile)
        try:
            server_module.write_project_log(project, "project_profile_saved_lightweight", profile=profile)
        except Exception:
            pass
        return {"success": True, "profile": profile}

    get_route = APIRoute(
        path="/api/projects/{project_id}/project-profile",
        endpoint=get_profile,
        methods=["GET"],
        name="get_lightweight_project_profile",
    )
    put_route = APIRoute(
        path="/api/projects/{project_id}/project-profile",
        endpoint=save_profile,
        methods=["PUT", "POST"],
        name="save_lightweight_project_profile",
    )
    _insert_before_existing(app, "/api/projects/{project_id}/project-profile", {"GET"}, get_route)
    _insert_before_existing(app, "/api/projects/{project_id}/project-profile", {"PUT", "POST"}, put_route)
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app") and hasattr(module, "Project")]


def _install_when_ready() -> None:
    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_LIGHTWEIGHT_PROJECT_PROFILE") and time.monotonic() - started_at < 120:
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(name="ppt-project-profile-lightweight", target=worker, daemon=True).start()


_install_when_ready()
