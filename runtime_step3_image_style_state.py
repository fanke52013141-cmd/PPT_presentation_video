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
    if not style.get("sample_reference_image_prompts") and system_content:
        style["sample_reference_image_prompts"] = [system_content]
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


def _step3_style_prompt(project: Any, server_module: ModuleType, refs_impl: ModuleType) -> str:
    image_style = _step3_style(project)
    fallback = ""
    try:
        fallback = server_module.build_image_style_prompt(server_module.read_style_tokens_data())
    except Exception:
        fallback = ""
    if not image_style:
        return fallback

    lines = ["Step 3 当前图片风格（优先级高于全局默认图片风格）："]
    for label, key in [
        ("来源", "source"),
        ("风格名称", "style_name"),
        ("风格摘要", "style_summary"),
        ("用户补充要求", "custom_requirement"),
    ]:
        value = _safe_text(image_style.get(key), 2000)
        if value:
            lines.append(f"- {label}: {value}")
    system_content = _safe_text(image_style.get("system_content"), 12000)
    if system_content:
        lines.append("- 生图 system content:")
        lines.extend(f"  {line}" for line in system_content.splitlines() if line.strip())
    visual_language = image_style.get("visual_language")
    if isinstance(visual_language, dict) and visual_language:
        lines.append("- 结构化视觉语言:")
        for key, value in visual_language.items():
            if isinstance(value, list):
                rendered = "、".join(str(item).strip() for item in value if str(item).strip())
            elif isinstance(value, dict):
                rendered = "；".join(f"{k}: {v}" for k, v in value.items() if str(v).strip())
            else:
                rendered = _safe_text(value, 1000)
            if rendered:
                lines.append(f"  - {key}: {rendered}")
    for title, key in [("Mask 友好规则", "maskability_rules"), ("负向规则", "negative_prompt_rules")]:
        values = image_style.get(key)
        if isinstance(values, list) and values:
            lines.append(f"- {title}:")
            lines.extend(f"  - {str(item).strip()}" for item in values if str(item).strip())
    try:
        has_refs = bool(refs_impl._project_reference_paths(project))
    except Exception:
        has_refs = False
    if has_refs:
        lines.append("- 当前 Step 3 已有 1-3 张图片风格参考图；兼容模型会把这些 PNG 作为 reference images 一起提交。")
    lines.extend([
        "- 不可覆盖规则：visual_draft.png 外背景必须保持纯白 #FFFFFF。",
        "- 不可覆盖规则：最终视频背景不能画进生图。",
        "- 不可覆盖规则：所有语义元素必须留出明显白色间隔，不能重叠、粘连或穿插。",
    ])
    if fallback:
        lines.append("\n全局图片风格模板（仅作为 fallback，若与 Step 3 当前风格冲突，以 Step 3 为准）：")
        lines.append(fallback)
    return "\n".join(lines)


def _patch_reference_style_source(refs_impl: ModuleType) -> None:
    if getattr(refs_impl, "__ppt_step3_style_source_patch__", False):
        return
    refs_impl._profile_image_style = _step3_style
    refs_impl._profile_style_prompt = lambda project, server_module: _step3_style_prompt(project, server_module, refs_impl)
    refs_impl._update_prompt_companion = _save_reference_images_to_step3_state
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
        state = _step3_style_state(project)
        return {"success": True, "style_state": state, "style": _step3_style(project)}

    def put_step3_style(project_id: str, payload: dict[str, Any], db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        style = _manual_style_from_payload(payload if isinstance(payload, dict) else {}, _step3_style(project))
        if not _safe_text(style.get("system_content"), 12000):
            raise server_module.HTTPException(status_code=400, detail="图片生成 System Content 不能为空")
        state = _save_step3_style(project, style, "manual_system_content")
        try:
            server_module.write_project_log(project, "step3_image_style_manual_saved", path=str(_state_path(project)))
        except Exception:
            pass
        return {"success": True, "style": style, "style_state": state}

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
        "/api/projects/{project_id}/steps/3/image-style",
        {"PUT"},
        APIRoute("/api/projects/{project_id}/steps/3/image-style", put_step3_style, methods=["PUT"], name="put_step3_image_style_state"),
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
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_STEP3_IMAGE_STYLE_STATE") and time.monotonic() - started_at < 120:
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(name="ppt-step3-image-style-state", target=worker, daemon=True).start()
