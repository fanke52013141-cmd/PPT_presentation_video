"""Step 3 image style state override.

New image style state belongs to Step 3 and is stored in
``planning/step3_image_style.json``. Legacy Project Profile image style is still
used as fallback for old projects.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_step3_image_style_state_patch__"
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


def _step3_style(project: Any) -> dict[str, Any]:
    state = _read_json(_state_path(project), {})
    if isinstance(state.get("image_style_profile"), dict):
        return state["image_style_profile"]
    legacy = _read_json(_profile_path(project), {}).get("image_style_profile")
    return legacy if isinstance(legacy, dict) else {}


def _save_step3_style(project: Any, style: dict[str, Any], source: str) -> dict[str, Any]:
    state = {
        "version": "step3_image_style_v1",
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "image_style_profile": style if isinstance(style, dict) else {},
        "note": "Step 3 owns image style. Project creation does not set image style.",
    }
    _write_json(_state_path(project), state)
    return state


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
        app.router.routes.append(route)
        return
    for index, existing in enumerate(routes):
        if str(getattr(existing, "path", "")) == path and methods.intersection(_route_methods(existing)):
            routes.insert(index, route)
            return
    routes.append(route)


def _patch_reference_style_source(refs_impl: ModuleType) -> None:
    if getattr(refs_impl, "__ppt_step3_style_source_patch__", False):
        return
    refs_impl._profile_image_style = _step3_style
    setattr(refs_impl, "__ppt_step3_style_source_patch__", True)


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db", "File", "Form")
    if not all(hasattr(server_module, name) for name in required):
        return False

    try:
        import runtime_image_style_reverse as reverse_impl
        import runtime_project_style_references as refs_impl
    except Exception:
        return False

    _patch_reference_style_source(refs_impl)

    from fastapi.routing import APIRoute

    app = server_module.app

    def get_step3_style(project_id: str, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        state = _read_json(_state_path(project), {})
        return {"success": True, "style_state": state, "style": _step3_style(project)}

    async def reverse_step3_style(
        project_id: str,
        files: list[Any] = server_module.File(...),
        requirement: str = server_module.Form(""),
        apply: bool = server_module.Form(True),
        db: Any = server_module.Depends(server_module.get_db),
    ) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        saved = reverse_impl._save_uploaded_references(server_module, project, files)
        requirement_text = reverse_impl._safe_text(requirement, 4000)
        raw_style = reverse_impl._call_vision_model(server_module, saved, project, requirement_text)
        style = reverse_impl._style_with_required_rules(raw_style, saved, requirement_text)
        state = _save_step3_style(project, style, "image_reverse_engineered") if apply else {}
        try:
            server_module.write_project_log(project, "step3_image_style_saved", style_name=style.get("style_name"), path=str(_state_path(project)))
        except Exception:
            pass
        return {"success": True, "style": style, "style_state": state, "inputs": saved}

    _insert_before_existing(
        app,
        "/api/projects/{project_id}/steps/3/image-style",
        {"GET"},
        APIRoute("/api/projects/{project_id}/steps/3/image-style", get_step3_style, methods=["GET"], name="get_step3_image_style_state"),
    )
    _insert_before_existing(
        app,
        "/api/projects/{project_id}/steps/3/image-style/reverse",
        {"POST"},
        APIRoute("/api/projects/{project_id}/steps/3/image-style/reverse", reverse_step3_style, methods=["POST"], name="reverse_step3_image_style_state"),
    )
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app") and hasattr(module, "Project")]


def _install_when_ready() -> None:
    def worker() -> None:
        while not os.environ.get("PPT_STUDIO_DISABLE_STEP3_IMAGE_STYLE_STATE"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(name="ppt-step3-image-style-state", target=worker, daemon=True).start()


_install_when_ready()
