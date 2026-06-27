"""Step 3 image-style API aliases.

Legacy Project Profile bridges remain as compatibility implementations. This
bridge exposes Step-3-scoped URLs so image style reverse engineering and style
reference management appear where they belong in the product flow: image
generation. Step 3 reverse style state is saved to planning/step3_image_style.json.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_step3_image_style_alias_patch__"
STATE_FILENAME = "step3_image_style.json"


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
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _save_step3_style_state(project: Any, style: dict[str, Any], source: str) -> dict[str, Any]:
    existing = _read_json(_step3_state_path(project), {})
    state = {
        "version": "step3_image_style_v1",
        "source": source,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "image_style_profile": style if isinstance(style, dict) else {},
        "reference_images": existing.get("reference_images", []) if isinstance(existing.get("reference_images"), list) else [],
        "note": "Step 3 owns image style. Project creation does not set image style.",
    }
    _write_json(_step3_state_path(project), state)
    return state


def _rewrite_reference_urls(value: Any, project_id: str) -> Any:
    if isinstance(value, dict):
        result = {key: _rewrite_reference_urls(item, project_id) for key, item in value.items()}
        if "index" in result and isinstance(result.get("url"), str):
            try:
                index = int(result.get("index"))
                result["url"] = f"/api/projects/{project_id}/steps/3/image-style/reference-images/{index}?t={int(time.time())}"
            except Exception:
                pass
        return result
    if isinstance(value, list):
        return [_rewrite_reference_urls(item, project_id) for item in value]
    return value


def _project_or_404(server_module: ModuleType, db: Any, project_id: str) -> Any:
    project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
    if not project:
        raise server_module.HTTPException(status_code=404, detail="项目不存在")
    return project


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db", "File", "Form", "FileResponse")
    if not all(hasattr(server_module, name) for name in required):
        return False

    try:
        import runtime_image_style_reverse as reverse_impl
        import runtime_project_style_references as refs_impl
        import runtime_project_style_reference_manager as manager_impl
    except Exception:
        return False

    app = server_module.app

    async def reverse_image_style_step3(
        project_id: str,
        files: list[Any] = server_module.File(...),
        requirement: str = server_module.Form(""),
        apply: bool = server_module.Form(True),
        db: Any = server_module.Depends(server_module.get_db),
    ) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        requirement_text = reverse_impl._safe_text(requirement, 4000)
        saved = reverse_impl._save_uploaded_references(server_module, project, files)
        raw_style = reverse_impl._call_vision_model(server_module, saved, project, requirement_text)
        style = reverse_impl._style_with_required_rules(raw_style, saved, requirement_text)
        style_state = _save_step3_style_state(project, style, "image_reverse_engineered") if apply else {}
        try:
            server_module.write_project_log(
                project,
                "step3_image_style_reverse_engineered",
                reference_count=len(saved),
                applied=bool(apply),
                style_name=style.get("style_name"),
                style_state=str(_step3_state_path(project)),
            )
        except Exception:
            pass
        return {"success": True, "style": style, "style_state": style_state, "inputs": saved}

    def list_reference_images_step3(project_id: str, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        references = refs_impl._load_manifest(project, project_id)
        return {"success": True, "references": _rewrite_reference_urls(references, project_id)}

    def generate_reference_images_step3(project_id: str, payload: dict[str, Any] | None = None, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        manifest = refs_impl._generate_reference_images(server_module, project, project_id, payload if isinstance(payload, dict) else {})
        return {"success": True, "references": _rewrite_reference_urls(manifest, project_id)}

    def get_reference_image_step3(project_id: str, index: int, db: Any = server_module.Depends(server_module.get_db)) -> Any:
        project = _project_or_404(server_module, db, project_id)
        if index < 1 or index > 3:
            raise server_module.HTTPException(status_code=404, detail="参考图不存在")
        path = refs_impl._references_dir(project) / f"style_reference_{index:02d}.png"
        try:
            path = Path(path).resolve()
            path.relative_to(refs_impl._references_dir(project).resolve())
        except Exception:
            raise server_module.HTTPException(status_code=404, detail="参考图不存在")
        if not path.exists() or not path.is_file():
            raise server_module.HTTPException(status_code=404, detail="参考图不存在")
        return server_module.FileResponse(str(path), media_type="image/png")

    def delete_reference_image_step3(project_id: str, index: int, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        try:
            references = manager_impl._delete_reference(project, project_id, int(index))
        except ValueError as exc:
            raise server_module.HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            server_module.write_project_log(project, "step3_image_style_reference_image_deleted", index=index)
        except Exception:
            pass
        return {"success": True, "references": _rewrite_reference_urls(references, project_id)}

    def delete_all_reference_images_step3(project_id: str, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        references = manager_impl._delete_all_references(project, project_id)
        try:
            server_module.write_project_log(project, "step3_image_style_reference_images_deleted", count=references.get("deleted_count", 0))
        except Exception:
            pass
        return {"success": True, "references": _rewrite_reference_urls(references, project_id)}

    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/reverse", reverse_image_style_step3, methods=["POST"])
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/reference-images", list_reference_images_step3, methods=["GET"])
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/reference-images/generate", generate_reference_images_step3, methods=["POST"])
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/reference-images/{index}", get_reference_image_step3, methods=["GET"])
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/reference-images/{index}", delete_reference_image_step3, methods=["DELETE"])
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/reference-images", delete_all_reference_images_step3, methods=["DELETE"])
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app") and hasattr(module, "Project")]


def _install_when_ready() -> None:
    def worker() -> None:
        while not os.environ.get("PPT_STUDIO_DISABLE_STEP3_IMAGE_STYLE"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(name="ppt-step3-image-style-runtime", target=worker, daemon=True).start()


_install_when_ready()
