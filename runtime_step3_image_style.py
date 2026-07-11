"""Step 3 image-style API aliases.

Legacy Project Profile bridges remain as compatibility implementations. This
bridge exposes Step-3-scoped URLs so image style reverse engineering and style
reference management appear where they belong in the product flow: image
generation. Step 3 reverse style state is saved to planning/step3_image_style.json.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

PATCH_MARKER = "__ppt_step3_image_style_alias_patch__"
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
    templates_root = Path(str(getattr(server_module, "DATA_DIR", Path(__file__).parent / "data"))) / "step3_image_style_templates"
    templates_index_path = templates_root / "index.json"

    def builtin_handdrawn_sources() -> tuple[Path, list[Path]]:
        repo_root = Path(str(getattr(server_module, "REPO_ROOT", Path(__file__).parent)))
        style_path = Path(str(getattr(server_module, "HANDDRAWN_STYLE_TOKENS_PATH", repo_root / "config" / "style_tokens_handdrawn.yaml")))
        reference_root = repo_root / "references" / "style_reference"
        reference_paths = [reference_root / "PPT模板.png", reference_root / "PPT示例.png"]
        return style_path, [path for path in reference_paths if path.exists() and path.is_file()]

    def builtin_handdrawn_style() -> dict[str, Any]:
        style_path, _ = builtin_handdrawn_sources()
        if not style_path.exists():
            raise server_module.HTTPException(status_code=404, detail="内置手绘风格配置缺失")
        try:
            style_tokens = yaml.safe_load(style_path.read_text(encoding="utf-8-sig")) or {}
        except Exception as exc:
            raise server_module.HTTPException(status_code=500, detail="内置手绘风格配置损坏") from exc
        if not isinstance(style_tokens, dict):
            raise server_module.HTTPException(status_code=500, detail="内置手绘风格配置损坏")
        system_content = server_module.build_image_style_prompt(style_tokens)
        return {
            "source": "built_in_template",
            "template_id": BUILTIN_HANDDRAWN_TEMPLATE_ID,
            "style_name": BUILTIN_HANDDRAWN_TEMPLATE_NAME,
            "style_summary": "温暖极简的手绘线稿科普风格，纯白画布、清晰分组，适合演讲内容可视化与 Mask 显现。",
            "system_content": system_content,
            "sample_reference_image_prompts": [system_content],
            "reference_image_count_target": 3,
            "style_tokens": style_tokens,
        }

    def builtin_handdrawn_detail() -> dict[str, Any]:
        _, reference_paths = builtin_handdrawn_sources()
        images = [
            {
                "index": index,
                "filename": path.name,
                "source": "built_in_template",
                "url": f"/api/image-style/project-templates/{BUILTIN_HANDDRAWN_TEMPLATE_ID}/reference-images/{index}?t={int(path.stat().st_mtime)}",
            }
            for index, path in enumerate(reference_paths[:3], start=1)
        ]
        item = {
            "id": BUILTIN_HANDDRAWN_TEMPLATE_ID,
            "name": BUILTIN_HANDDRAWN_TEMPLATE_NAME,
            "built_in": True,
            "reference_count": len(images),
        }
        return {
            "success": True,
            "template": item,
            "style": builtin_handdrawn_style(),
            "references": {
                "scope": "step3_image_style_template",
                "style_name": BUILTIN_HANDDRAWN_TEMPLATE_NAME,
                "images": images,
            },
        }

    def read_templates() -> list[dict[str, Any]]:
        value = _read_json(templates_index_path, {"templates": []})
        items = value.get("templates", []) if isinstance(value, dict) else []
        return [item for item in items if isinstance(item, dict)]

    def write_templates(items: list[dict[str, Any]]) -> None:
        _write_json(templates_index_path, {"version": "step3_image_style_templates_v1", "templates": items})

    def template_dir_or_404(template_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{12}", str(template_id or "")):
            raise server_module.HTTPException(status_code=404, detail="图片风格模板不存在")
        path = (templates_root / template_id).resolve()
        if path.parent != templates_root.resolve() or not path.exists():
            raise server_module.HTTPException(status_code=404, detail="图片风格模板不存在")
        return path

    def list_step3_templates() -> dict[str, Any]:
        _, reference_paths = builtin_handdrawn_sources()
        built_in = {
            "id": BUILTIN_HANDDRAWN_TEMPLATE_ID,
            "name": BUILTIN_HANDDRAWN_TEMPLATE_NAME,
            "built_in": True,
            "reference_count": min(3, len(reference_paths)),
        }
        return {"success": True, "templates": [built_in, *read_templates()]}

    def step3_template_detail(template_id: str) -> dict[str, Any]:
        if template_id == BUILTIN_HANDDRAWN_TEMPLATE_ID:
            return builtin_handdrawn_detail()
        source = template_dir_or_404(template_id)
        style = _read_json(source / "style.json", {})
        manifest = _read_json(source / "references.json", {})
        images = manifest.get("images", []) if isinstance(manifest, dict) else []
        normalized_images: list[dict[str, Any]] = []
        for item in images[:3]:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
            except Exception:
                continue
            filename = Path(str(item.get("filename") or f"style_reference_{index:02d}.png")).name
            path = (source / "references" / filename).resolve()
            try:
                path.relative_to((source / "references").resolve())
            except ValueError:
                continue
            if not path.exists() or not path.is_file():
                continue
            normalized_images.append({
                **item,
                "index": index,
                "filename": filename,
                "url": f"/api/image-style/project-templates/{template_id}/reference-images/{index}?t={int(path.stat().st_mtime)}",
            })
        item = next((entry for entry in read_templates() if str(entry.get("id") or "") == template_id), {})
        return {
            "success": True,
            "template": item,
            "style": style if isinstance(style, dict) else {},
            "references": {
                "scope": "step3_image_style_template",
                "style_name": str((style or {}).get("style_name") or item.get("name") or ""),
                "images": normalized_images,
            },
        }

    def get_step3_template_detail(template_id: str) -> dict[str, Any]:
        return step3_template_detail(template_id)

    def get_step3_template_reference(template_id: str, index: int) -> Any:
        if template_id == BUILTIN_HANDDRAWN_TEMPLATE_ID:
            _, reference_paths = builtin_handdrawn_sources()
            if index < 1 or index > len(reference_paths):
                raise server_module.HTTPException(status_code=404, detail="模板参考图不存在")
            return server_module.FileResponse(str(reference_paths[index - 1]), media_type="image/png")
        source = template_dir_or_404(template_id)
        detail = step3_template_detail(template_id)
        image = next((item for item in detail["references"]["images"] if int(item.get("index", 0)) == int(index)), None)
        if image is None:
            raise server_module.HTTPException(status_code=404, detail="模板参考图不存在")
        path = (source / "references" / Path(str(image.get("filename") or "")).name).resolve()
        try:
            path.relative_to((source / "references").resolve())
        except ValueError as exc:
            raise server_module.HTTPException(status_code=404, detail="模板参考图不存在") from exc
        return server_module.FileResponse(str(path), media_type="image/png")

    def save_step3_template(
        project_id: str,
        payload: dict[str, Any],
        db: Any = server_module.Depends(server_module.get_db),
    ) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        name = str((payload or {}).get("name") or "").strip()
        if not name:
            raise server_module.HTTPException(status_code=400, detail="模板名称不能为空")
        if len(name) > 120:
            raise server_module.HTTPException(status_code=400, detail="模板名称不能超过 120 个字符")
        state = _read_json(_step3_state_path(project), {})
        style = state.get("image_style_profile") if isinstance(state.get("image_style_profile"), dict) else {}
        if not str(style.get("system_content") or "").strip():
            raise server_module.HTTPException(status_code=400, detail="请先保存图片生成 System Content")
        manifest = _read_json(manager_impl._manifest_path(project), {})
        manifest_images = manifest.get("images", []) if isinstance(manifest, dict) else []
        if not manifest_images:
            raise server_module.HTTPException(status_code=400, detail="请先生成或上传至少 1 张效果预览")
        items = read_templates()
        if any(str(item.get("name") or "").strip().casefold() == name.casefold() for item in items):
            raise server_module.HTTPException(status_code=400, detail="模板名称已存在，请换一个名称")
        template_id = uuid.uuid4().hex[:12]
        target = templates_root / template_id
        target.mkdir(parents=True, exist_ok=False)
        _write_json(target / "style.json", style)
        _write_json(target / "references.json", manifest if isinstance(manifest, dict) else {})
        source_refs = manager_impl._references_dir(project)
        if source_refs.exists():
            shutil.copytree(source_refs, target / "references", dirs_exist_ok=True)
        item = {
            "id": template_id,
            "name": name,
            "reference_count": len((manifest or {}).get("images", [])) if isinstance(manifest, dict) else 0,
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        items.append(item)
        write_templates(items)
        return {"success": True, "template": item, "templates": items}

    def apply_step3_template(
        project_id: str,
        template_id: str,
        db: Any = server_module.Depends(server_module.get_db),
    ) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        built_in = template_id == BUILTIN_HANDDRAWN_TEMPLATE_ID
        source = None if built_in else template_dir_or_404(template_id)
        style = builtin_handdrawn_style() if built_in else _read_json(source / "style.json", {})
        if not style:
            raise server_module.HTTPException(status_code=400, detail="图片风格模板内容损坏")
        _save_step3_style_state(project, style, "built_in_template" if built_in else "named_template")
        target_refs = manager_impl._references_dir(project)
        if target_refs.exists():
            shutil.rmtree(target_refs)
        if built_in:
            _, source_images = builtin_handdrawn_sources()
            target_refs.mkdir(parents=True, exist_ok=True)
            images = []
            for index, source_image in enumerate(source_images[:3], start=1):
                filename = f"style_reference_{index:02d}.png"
                target = target_refs / filename
                processor = getattr(server_module, "process_and_save_image", None)
                if callable(processor):
                    processor(source_image.read_bytes(), str(target))
                else:
                    shutil.copy2(source_image, target)
                images.append({"index": index, "filename": filename, "source": "built_in_template"})
            manifest = {
                "version": "step3_style_references_v1",
                "scope": "step3_image_style",
                "style_name": BUILTIN_HANDDRAWN_TEMPLATE_NAME,
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "images": images,
            }
        else:
            source_refs = source / "references"
            if source_refs.exists():
                shutil.copytree(source_refs, target_refs)
            manifest = _read_json(source / "references.json", {})
        manager_impl._write_normalized_manifest(project, manifest if isinstance(manifest, dict) else {})
        references = refs_impl._load_manifest(project, project_id)
        return {
            "success": True,
            "style": style,
            "references": _rewrite_reference_urls(references, project_id),
        }

    def delete_step3_template(template_id: str) -> dict[str, Any]:
        if template_id == BUILTIN_HANDDRAWN_TEMPLATE_ID:
            raise server_module.HTTPException(status_code=400, detail="内置手绘风格不能删除")
        source = template_dir_or_404(template_id)
        items = [item for item in read_templates() if str(item.get("id") or "") != template_id]
        shutil.rmtree(source)
        write_templates(items)
        return {"success": True, "templates": items}

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

    async def upload_reference_images_step3(
        project_id: str,
        files: list[Any] = server_module.File(...),
        db: Any = server_module.Depends(server_module.get_db),
    ) -> dict[str, Any]:
        project = _project_or_404(server_module, db, project_id)
        selected = [file for file in (files or []) if file is not None]
        if not selected:
            raise server_module.HTTPException(status_code=400, detail="请上传 1-3 张参考图")
        if len(selected) > 3:
            raise server_module.HTTPException(status_code=400, detail="最多只能上传 3 张参考图")
        refs_dir = refs_impl._references_dir(project)
        refs_dir.mkdir(parents=True, exist_ok=True)
        uploaded: list[dict[str, Any]] = []
        for index, file in enumerate(selected, start=1):
            content = await file.read()
            if not content:
                continue
            filename = f"style_reference_{index:02d}.png"
            save_path = refs_dir / filename
            processor = getattr(server_module, "process_and_save_image", None)
            if callable(processor):
                processor(content, str(save_path))
            else:
                save_path.write_bytes(content)
            uploaded.append({
                "index": index,
                "filename": filename,
                "prompt": f"手动上传参考图：{Path(str(getattr(file, 'filename', '') or filename)).name}",
                "source": "manual_upload",
                "uploaded_at": datetime.now().isoformat(timespec="seconds"),
                "url": f"/api/projects/{project_id}/steps/3/image-style/reference-images/{index}?t={int(time.time())}",
            })
        if not uploaded:
            raise server_module.HTTPException(status_code=400, detail="参考图文件为空")
        manifest = {
            "version": "step3_style_references_v1",
            "legacy_version": "project_style_references_v1",
            "scope": "step3_image_style",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "style_name": "手动上传参考图",
            "images": uploaded,
        }
        manager_impl._write_normalized_manifest(project, manifest)
        try:
            server_module.write_project_log(project, "step3_image_style_reference_images_uploaded", count=len(uploaded))
        except Exception:
            pass
        return {"success": True, "references": _rewrite_reference_urls(refs_impl._load_manifest(project, project_id), project_id)}

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
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/reference-images", upload_reference_images_step3, methods=["POST"])
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/reference-images/generate", generate_reference_images_step3, methods=["POST"])
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/reference-images/{index}", get_reference_image_step3, methods=["GET"])
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/reference-images/{index}", delete_reference_image_step3, methods=["DELETE"])
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/reference-images", delete_all_reference_images_step3, methods=["DELETE"])
    app.add_api_route("/api/image-style/project-templates", list_step3_templates, methods=["GET"])
    app.add_api_route("/api/image-style/project-templates/{template_id}", get_step3_template_detail, methods=["GET"])
    app.add_api_route("/api/image-style/project-templates/{template_id}/reference-images/{index}", get_step3_template_reference, methods=["GET"])
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/templates", save_step3_template, methods=["POST"])
    app.add_api_route("/api/projects/{project_id}/steps/3/image-style/templates/{template_id}/apply", apply_step3_template, methods=["POST"])
    app.add_api_route("/api/image-style/project-templates/{template_id}", delete_step3_template, methods=["DELETE"])
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app") and hasattr(module, "Project")]


def _install_when_ready() -> None:
    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_STEP3_IMAGE_STYLE") and time.monotonic() - started_at < 120:
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(name="ppt-step3-image-style-runtime", target=worker, daemon=True).start()
