"""Delayed Step 3 integration for project-local style reference images.

`runtime_project_style_references` registers project-local reference image APIs.
This bridge waits until the large `server.py` module has finished defining Step 3
helpers, then prepends project-aware Step 3 routes:

- prompt preview uses Project Profile image style text;
- image generation uses planning/style_references/*.png as binary reference
  images when the configured image model supports reference editing.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from pathlib import Path
from types import ModuleType
from typing import Any

try:
    from runtime_project_style_references import (  # type: ignore
        _can_send_project_references,
        _project_generate_prompt_for_slide,
        _project_reference_paths,
        _read_json,
        _run_dir,
        _safe_text,
    )
except Exception:  # pragma: no cover - optional runtime bridge
    _can_send_project_references = None
    _project_generate_prompt_for_slide = None
    _project_reference_paths = None
    _read_json = None
    _run_dir = None
    _safe_text = None


STEP3_ROUTES_MARKER = "__ppt_project_style_references_step3_routes__"
INSTALL_TIMEOUT_SEC = 120.0


def _insert_route_before_existing(app: Any, path: str, endpoint: Any, methods: list[str], name: str) -> None:
    routes = app.router.routes
    for route in routes:
        if getattr(route, "name", "") == name:
            return
    method_set = {method.upper() for method in methods}
    insert_index = len(routes)
    for idx, route in enumerate(routes):
        if getattr(route, "path", None) == path and method_set.intersection(set(getattr(route, "methods", set()) or set())):
            insert_index = idx
            break
    app.add_api_route(path, endpoint, methods=methods, name=name)
    new_route = routes.pop()
    routes.insert(insert_index, new_route)


def _required_ready(server_module: ModuleType) -> bool:
    if not all([_can_send_project_references, _project_generate_prompt_for_slide, _project_reference_paths, _read_json, _run_dir, _safe_text]):
        return False
    required = (
        "app", "Form", "Depends", "get_db", "Project", "HTTPException",
        "read_current_slide_ids_or_404", "get_setting", "get_openai_client",
        "enforce_white_generation_background", "generate_image_response",
        "extract_image_bytes_from_response", "process_and_save_image", "mark_slide_image_changed",
        "compact_slide_element_lines",
    )
    return all(hasattr(server_module, name) for name in required)


def _install_step3_routes(server_module: ModuleType) -> bool:
    if not _required_ready(server_module):
        return False
    app = server_module.app
    if getattr(app.state, STEP3_ROUTES_MARKER, False):
        return True

    def get_slide_prompts_with_project_style(project_id: str, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        contract_path = _run_dir(project) / "planning" / "visual_contract.json"
        if not contract_path.exists():
            raise server_module.HTTPException(status_code=400, detail="分镜规划尚未生成")
        contract = _read_json(contract_path, {})
        topic = contract.get("topic") if isinstance(contract.get("topic"), dict) else {}
        topic_name = topic.get("topic_name") or getattr(project, "name", "")
        slide_prompts = []
        for slide in contract.get("slides", []) if isinstance(contract.get("slides"), list) else []:
            if not isinstance(slide, dict):
                continue
            slide_id = _safe_text(slide.get("slide_id"), 100)
            if not slide_id:
                continue
            slide_prompts.append({
                "slide_id": slide_id,
                "title": slide.get("main_title") or slide_id,
                "prompt": _project_generate_prompt_for_slide(server_module, project, slide, str(topic_name or "")),
            })
        return {"success": True, "prompts": slide_prompts}

    def generate_slide_image_with_project_refs(
        project_id: str,
        slide_id: str = server_module.Form(...),
        prompt: str = server_module.Form(...),
        preview: bool = server_module.Form(False),
        db: Any = server_module.Depends(server_module.get_db),
    ) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        if slide_id not in server_module.read_current_slide_ids_or_404(project):
            raise server_module.HTTPException(status_code=404, detail="Slide 不存在")

        api_key = server_module.get_setting("image_api_key")
        base_url = server_module.get_setting("image_base_url")
        model = server_module.get_setting("image_model", "gpt-image-1")
        image_filename = "visual_candidate.png" if preview else "visual_draft.png"
        save_path = Path(_run_dir(project)) / "slides" / slide_id / image_filename
        if not api_key:
            raise server_module.HTTPException(status_code=400, detail="未配置生图 API 密钥，请在系统设置中配置，或使用下方本地上传图片功能。")

        project_reference_paths = _project_reference_paths(project)
        used_project_style_references = False
        try:
            client = server_module.get_openai_client(api_key=api_key, base_url=base_url)
            image_size = server_module.get_setting("image_size", "1024x1024")
            effective_prompt = server_module.enforce_white_generation_background(prompt)
            response = None

            if _can_send_project_references(server_module, model, base_url, project_reference_paths):
                reference_files = []
                try:
                    reference_files = [open(path, "rb") for path in project_reference_paths]
                    response = client.images.edit(
                        model=model,
                        image=reference_files,
                        prompt=effective_prompt,
                        size=image_size,
                        n=1,
                    )
                    used_project_style_references = True
                    try:
                        server_module.write_project_log(
                            project,
                            "step3_project_style_references_used",
                            slide_id=slide_id,
                            reference_count=len(project_reference_paths),
                            model=model,
                        )
                    except Exception:
                        pass
                except Exception as reference_error:
                    try:
                        server_module.logger.warning(
                            "Project style reference images unavailable for %s; falling back to normal image generation: %s",
                            slide_id,
                            reference_error,
                        )
                    except Exception:
                        pass
                finally:
                    for reference_file in reference_files:
                        reference_file.close()

            if response is None:
                response = server_module.generate_image_response(
                    client=client,
                    model=model,
                    prompt=effective_prompt,
                    size=image_size,
                    base_url=base_url,
                )
            img_bytes = server_module.extract_image_bytes_from_response(response)
            server_module.process_and_save_image(img_bytes, str(save_path))
            if preview:
                return {
                    "success": True,
                    "candidate_url": f"/api/projects/{project_id}/slides/{slide_id}/candidate?t={uuid.uuid4().hex[:6]}",
                    "used_project_style_references": used_project_style_references,
                    "project_style_reference_count": len(project_reference_paths),
                }
            server_module.mark_slide_image_changed(project, slide_id, db)
            return {
                "success": True,
                "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}",
                "used_project_style_references": used_project_style_references,
                "project_style_reference_count": len(project_reference_paths),
            }
        except Exception as exc:
            try:
                server_module.logger.error("Image generation error for %s: %s", slide_id, exc)
            except Exception:
                pass
            raise server_module.HTTPException(status_code=500, detail=f"生成图片失败: {exc}") from exc

    _insert_route_before_existing(
        app,
        "/api/projects/{project_id}/steps/3/prompts",
        get_slide_prompts_with_project_style,
        ["GET"],
        "get_slide_prompts_with_project_style",
    )
    _insert_route_before_existing(
        app,
        "/api/projects/{project_id}/steps/3/generate",
        generate_slide_image_with_project_refs,
        ["POST"],
        "generate_slide_image_with_project_refs",
    )
    setattr(app.state, STEP3_ROUTES_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app") and hasattr(module, "Project")]


def _log_timeout() -> None:
    for module in _candidate_modules():
        logger = getattr(module, "logger", None)
        if logger:
            logger.warning("Project style Step 3 bridge was not installed within %.0f seconds; helper functions may be missing.", INSTALL_TIMEOUT_SEC)
            return


def _install_when_ready() -> None:
    def worker() -> None:
        started_at = time.monotonic()
        while not os.environ.get("PPT_STUDIO_DISABLE_PROJECT_STYLE_REFERENCES"):
            for module in _candidate_modules():
                try:
                    if _install_step3_routes(module):
                        return
                except Exception:
                    pass
            if time.monotonic() - started_at > INSTALL_TIMEOUT_SEC:
                _log_timeout()
                return
            time.sleep(0.1)
    threading.Thread(name="ppt-project-style-step3-runtime", target=worker, daemon=True).start()


_install_when_ready()
