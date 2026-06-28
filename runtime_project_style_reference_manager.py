"""Step 3 image style reference manager compatibility bridge.

The legacy project-profile reference routes are still used as implementation
helpers, but the product-facing UI now calls the Step 3 aliases exposed by
``runtime_step3_image_style.py``. Deleting or clearing references also syncs
``planning/step3_image_style.json`` so Step 3 prompt generation does not keep
stale reference-image state.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_project_style_reference_manager_patch__"
REFERENCE_DIRNAME = "style_references"
REFERENCE_MANIFEST = "project_style_references.json"
STEP3_STYLE_STATE = "step3_image_style.json"
STYLE_REFERENCE_VERSION = "step3_style_references_v1"
LEGACY_STYLE_REFERENCE_VERSION = "project_style_references_v1"


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def _manifest_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / REFERENCE_MANIFEST


def _step3_style_state_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / STEP3_STYLE_STATE


def _references_dir(project: Any) -> Path:
    return _run_dir(project) / "planning" / REFERENCE_DIRNAME


def _safe_text(value: Any, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]


def _safe_reference_path(project: Any, filename: Any) -> Path | None:
    refs_dir = _references_dir(project).resolve()
    name = Path(_safe_text(filename, 200)).name
    if not name:
        return None
    candidate = (refs_dir / name).resolve()
    try:
        candidate.relative_to(refs_dir)
    except ValueError:
        return None
    return candidate


def _reference_url(project_id: str, index: int) -> str:
    # Legacy route kept for compatibility. Step 3 aliases rewrite this URL for the UI.
    return f"/api/projects/{project_id}/project-profile/image-style/reference-images/{index}?t={int(time.time())}"


def _normalize_manifest(project: Any, project_id: str) -> dict[str, Any]:
    manifest = _read_json(_manifest_path(project), {})
    if not isinstance(manifest, dict):
        manifest = {}
    images = manifest.get("images") if isinstance(manifest.get("images"), list) else []
    normalized: list[dict[str, Any]] = []
    for item in images:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except Exception:
            continue
        path = _safe_reference_path(project, item.get("filename"))
        if path is None or not path.exists():
            continue
        normalized.append({
            **item,
            "index": index,
            "filename": path.name,
            "url": _reference_url(project_id, index),
        })
    normalized.sort(key=lambda item: int(item.get("index") or 0))
    return {
        "version": STYLE_REFERENCE_VERSION,
        "legacy_version": LEGACY_STYLE_REFERENCE_VERSION,
        "scope": "step3_image_style",
        "deprecated_route": True,
        "preferred_route": f"/api/projects/{project_id}/steps/3/image-style/reference-images",
        "updated_at": _safe_text(manifest.get("updated_at"), 80),
        "style_name": _safe_text(manifest.get("style_name"), 120),
        "images": normalized,
    }


def _sync_step3_style_references(project: Any, manifest: dict[str, Any]) -> None:
    state_path = _step3_style_state_path(project)
    state = _read_json(state_path, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("version", "step3_image_style_v1")
    state.setdefault("source", "reference_images")
    state.setdefault("image_style_profile", {})
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    state["reference_images"] = manifest.get("images", []) if isinstance(manifest.get("images"), list) else []
    state["note"] = "Step 3 owns image style. Project creation does not set image style."
    _write_json(state_path, state)


def _write_normalized_manifest(project: Any, manifest: dict[str, Any]) -> None:
    cleaned = {
        "version": STYLE_REFERENCE_VERSION,
        "legacy_version": LEGACY_STYLE_REFERENCE_VERSION,
        "scope": "step3_image_style",
        "updated_at": _safe_text(manifest.get("updated_at"), 80) or time.strftime("%Y-%m-%dT%H:%M:%S"),
        "style_name": _safe_text(manifest.get("style_name"), 120),
        "images": manifest.get("images", []),
    }
    _write_json(_manifest_path(project), cleaned)
    _sync_step3_style_references(project, cleaned)

    companion_path = _run_dir(project) / "planning" / "project_profile_prompt_companion.json"
    companion = _read_json(companion_path, {})
    if not isinstance(companion, dict):
        companion = {}
    companion["style_reference_images"] = cleaned["images"]
    companion["legacy_compatibility_only"] = True
    companion["preferred_state_file"] = f"planning/{STEP3_STYLE_STATE}"
    _write_json(companion_path, companion)


def _delete_reference(project: Any, project_id: str, index: int) -> dict[str, Any]:
    if index < 1 or index > 3:
        raise ValueError("参考图索引必须是 1-3")
    manifest = _normalize_manifest(project, project_id)
    kept = []
    deleted = False
    for item in manifest.get("images", []):
        if int(item.get("index") or 0) == index:
            path = _safe_reference_path(project, item.get("filename"))
            if path is not None:
                try:
                    if path.exists() and path.is_file():
                        path.unlink()
                except OSError:
                    pass
            deleted = True
            continue
        kept.append(item)
    manifest["images"] = kept
    manifest["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_normalized_manifest(project, manifest)
    result = _normalize_manifest(project, project_id)
    result["deleted"] = deleted
    return result


def _delete_all_references(project: Any, project_id: str) -> dict[str, Any]:
    refs_dir = _references_dir(project).resolve()
    deleted_count = 0
    if refs_dir.exists():
        for path in refs_dir.glob("style_reference_*.png"):
            try:
                if path.resolve().is_file() and path.resolve().parent == refs_dir:
                    path.unlink()
                    deleted_count += 1
            except OSError:
                pass
    manifest = {
        "version": STYLE_REFERENCE_VERSION,
        "legacy_version": LEGACY_STYLE_REFERENCE_VERSION,
        "scope": "step3_image_style",
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "images": [],
    }
    _write_normalized_manifest(project, manifest)
    result = _normalize_manifest(project, project_id)
    result["deleted_count"] = deleted_count
    return result


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db")
    if not all(hasattr(server_module, name) for name in required):
        return False
    app = server_module.app

    def delete_reference_image(project_id: str, index: int, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        try:
            references = _delete_reference(project, project_id, int(index))
        except ValueError as exc:
            raise server_module.HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            server_module.write_project_log(project, "legacy_step3_style_reference_image_deleted", index=index)
        except Exception:
            pass
        return {
            "success": True,
            "references": references,
            "deprecated_route": True,
            "preferred_route": f"/api/projects/{project_id}/steps/3/image-style/reference-images/{index}",
        }

    def delete_all_reference_images(project_id: str, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        references = _delete_all_references(project, project_id)
        try:
            server_module.write_project_log(project, "legacy_step3_style_reference_images_deleted", count=references.get("deleted_count", 0))
        except Exception:
            pass
        return {
            "success": True,
            "references": references,
            "deprecated_route": True,
            "preferred_route": f"/api/projects/{project_id}/steps/3/image-style/reference-images",
        }

    app.add_api_route("/api/projects/{project_id}/project-profile/image-style/reference-images/{index}", delete_reference_image, methods=["DELETE"])
    app.add_api_route("/api/projects/{project_id}/project-profile/image-style/reference-images", delete_all_reference_images, methods=["DELETE"])
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app") and hasattr(module, "Project")]


def _install_when_ready() -> None:
    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_PROJECT_STYLE_REFERENCE_MANAGER") and time.monotonic() - started_at < 120:
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(name="ppt-project-style-reference-manager-runtime", target=worker, daemon=True).start()


_install_when_ready()
