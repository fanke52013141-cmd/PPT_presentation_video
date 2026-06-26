"""Project-local image style reference generation and Step 3 integration.

This bridge turns Project Profile `sample_reference_image_prompts` into 1-3
project-local PNG reference images. The generated images are stored under the
run's planning directory and tracked by planning/project_style_references.json.

It also prepends project-aware Step 3 routes so the local UI uses the project
Profile image style in prompt previews and sends project-local reference PNGs to
compatible image-generation models.

The feature is intentionally project-scoped: it does not overwrite global
config/style_tokens.yaml or global image-style reference images.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_project_style_references_patch__"
STEP3_ROUTES_MARKER = "__ppt_project_style_references_step3_routes__"
REFERENCE_DIRNAME = "style_references"
REFERENCE_MANIFEST = "project_style_references.json"


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


def _safe_text(value: Any, limit: int = 8000) -> str:
    return str(value or "").strip()[:limit]


def _safe_count(value: Any, default: int = 3) -> int:
    try:
        parsed = int(float(str(value).strip()))
    except Exception:
        parsed = default
    return max(1, min(3, parsed))


def _run_dir(project: Any) -> Path:
    return Path(str(project.run_dir)).resolve()


def _profile_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / "project_profile.json"


def _manifest_path(project: Any) -> Path:
    return _run_dir(project) / "planning" / REFERENCE_MANIFEST


def _references_dir(project: Any) -> Path:
    return _run_dir(project) / "planning" / REFERENCE_DIRNAME


def _profile_image_style(project: Any) -> dict[str, Any]:
    profile = _read_json(_profile_path(project), {})
    if not isinstance(profile, dict):
        return {}
    image_style = profile.get("image_style_profile")
    return image_style if isinstance(image_style, dict) else {}


def _reference_prompts(image_style: dict[str, Any], count: int) -> list[str]:
    prompts = image_style.get("sample_reference_image_prompts")
    if isinstance(prompts, list):
        result = [_safe_text(item, 4000) for item in prompts if _safe_text(item, 4000)]
    else:
        result = []
    if not result:
        style_name = _safe_text(image_style.get("style_name"), 120) or "project image style"
        summary = _safe_text(image_style.get("style_summary"), 1000)
        system_content = _safe_text(image_style.get("system_content"), 3000)
        result = [
            (
                f"Create a 16:9 PPT image style reference sheet for {style_name}. "
                f"{summary}\n{system_content}\n"
                "Use separated visual groups, concise title text, simple icons, arrows, and labels. "
                "Keep the entire outer canvas pure-white #FFFFFF. Do not use texture background."
            )
        ]
    return result[:count]


def _style_generation_prompt(raw_prompt: str, image_style: dict[str, Any], index: int) -> str:
    style_name = _safe_text(image_style.get("style_name"), 120)
    style_summary = _safe_text(image_style.get("style_summary"), 1000)
    maskability_rules = image_style.get("maskability_rules") if isinstance(image_style.get("maskability_rules"), list) else []
    negative_rules = image_style.get("negative_prompt_rules") if isinstance(image_style.get("negative_prompt_rules"), list) else []
    return "\n".join(
        part
        for part in [
            f"Generate project image style reference #{index}.",
            f"Style name: {style_name}" if style_name else "",
            f"Style summary: {style_summary}" if style_summary else "",
            "Reference prompt:",
            raw_prompt,
            "Non-overridable production constraints:",
            "- 16:9 PPT-style image, centered composition, clean readable layout.",
            "- Entire outer canvas must be flat pure-white #FFFFFF; all four edges and corners stay continuously white.",
            "- Do not draw final-video background colors, background images, texture paper, gradients, shadows, vignettes, or noise into the outer canvas.",
            "- Keep 3-5 example semantic visual groups separated by clear white gaps for AI Mask and manual Mask reveal.",
            "- No overlap, no touching, no sticking between text, icons, arrows, labels, borders, formulas, people, or decorative marks.",
            "Maskability rules:\n" + "\n".join(f"- {str(rule).strip()}" for rule in maskability_rules if str(rule).strip()) if maskability_rules else "",
            "Negative rules:\n" + "\n".join(f"- {str(rule).strip()}" for rule in negative_rules if str(rule).strip()) if negative_rules else "",
            "Only output the image. Do not add production notes or UI elements.",
        ]
        if str(part).strip()
    )


def _image_url(project_id: str, index: int) -> str:
    return f"/api/projects/{project_id}/project-profile/image-style/reference-images/{index}?t={uuid.uuid4().hex[:8]}"


def _load_manifest(project: Any, project_id: str) -> dict[str, Any]:
    manifest = _read_json(_manifest_path(project), {})
    if not isinstance(manifest, dict):
        manifest = {}
    images = manifest.get("images") if isinstance(manifest.get("images"), list) else []
    normalized = []
    for item in images:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except Exception:
            continue
        filename = _safe_text(item.get("filename"), 200)
        if not filename:
            continue
        path = _references_dir(project) / filename
        if not path.exists():
            continue
        normalized.append({
            **item,
            "index": index,
            "filename": filename,
            "url": _image_url(project_id, index),
        })
    return {
        "version": "project_style_references_v1",
        "updated_at": _safe_text(manifest.get("updated_at")),
        "images": normalized,
    }


def _project_reference_paths(project: Any) -> list[str]:
    manifest = _read_json(_manifest_path(project), {})
    refs_dir = _references_dir(project)
    candidates: list[Path] = []
    if isinstance(manifest, dict) and isinstance(manifest.get("images"), list):
        for item in manifest["images"]:
            if not isinstance(item, dict):
                continue
            filename = _safe_text(item.get("filename"), 200)
            if filename:
                candidates.append(refs_dir / filename)
    if not candidates and refs_dir.exists():
        candidates = sorted(refs_dir.glob("style_reference_*.png"))[:3]
    result: list[str] = []
    for path in candidates[:3]:
        try:
            if path.exists() and path.is_file():
                result.append(str(path))
        except OSError:
            continue
    return result


def _update_prompt_companion(project: Any, manifest: dict[str, Any]) -> None:
    companion_path = _run_dir(project) / "planning" / "project_profile_prompt_companion.json"
    companion = _read_json(companion_path, {})
    if not isinstance(companion, dict):
        companion = {}
    companion["style_reference_images"] = manifest.get("images", [])
    _write_json(companion_path, companion)


def _generate_reference_images(server_module: ModuleType, project: Any, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    image_style = _profile_image_style(project)
    if not image_style:
        raise server_module.HTTPException(status_code=400, detail="Project Profile 中没有 image_style_profile")

    requested_count = _safe_count(payload.get("count") or image_style.get("reference_image_count_target") or 3)
    prompts = _reference_prompts(image_style, requested_count)
    if not prompts:
        raise server_module.HTTPException(status_code=400, detail="没有可用于生成参考图的 sample_reference_image_prompts")

    get_setting = getattr(server_module, "get_setting", None)
    if not callable(get_setting):
        raise server_module.HTTPException(status_code=500, detail="当前服务无法读取生图设置")
    api_key = _safe_text(get_setting("image_api_key"), 4000)
    base_url = _safe_text(get_setting("image_base_url"), 1000) or None
    model = _safe_text(get_setting("image_model", "gpt-image-1"), 200) or "gpt-image-1"
    image_size = _safe_text(get_setting("image_size", "1024x1024"), 100) or "1024x1024"
    if not api_key:
        raise server_module.HTTPException(status_code=400, detail="未配置生图 API 密钥，请先在系统设置中配置")

    required_helpers = ["get_openai_client", "generate_image_response", "extract_image_bytes_from_response", "process_and_save_image"]
    for name in required_helpers:
        if not callable(getattr(server_module, name, None)):
            raise server_module.HTTPException(status_code=500, detail=f"当前服务缺少生图辅助函数: {name}")

    client = server_module.get_openai_client(api_key=api_key, base_url=base_url, timeout=180.0, max_retries=0)
    references_dir = _references_dir(project)
    references_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    for index, raw_prompt in enumerate(prompts, start=1):
        final_prompt = _style_generation_prompt(raw_prompt, image_style, index)
        response = server_module.generate_image_response(
            client=client,
            model=model,
            prompt=final_prompt,
            size=image_size,
            base_url=base_url,
        )
        img_bytes = server_module.extract_image_bytes_from_response(response)
        filename = f"style_reference_{index:02d}.png"
        save_path = references_dir / filename
        server_module.process_and_save_image(img_bytes, str(save_path))
        generated.append({
            "index": index,
            "filename": filename,
            "prompt": raw_prompt,
            "model": model,
            "image_size": image_size,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "url": _image_url(project_id, index),
        })

    manifest = {
        "version": "project_style_references_v1",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "style_name": _safe_text(image_style.get("style_name"), 120),
        "images": generated,
    }
    _write_json(_manifest_path(project), manifest)
    _update_prompt_companion(project, manifest)
    try:
        server_module.write_project_log(
            project,
            "project_style_reference_images_generated",
            count=len(generated),
            model=model,
            image_size=image_size,
            manifest=str(_manifest_path(project)),
        )
    except Exception:
        pass
    return manifest


def _profile_style_prompt(project: Any, server_module: ModuleType) -> str:
    image_style = _profile_image_style(project)
    fallback = ""
    try:
        fallback = server_module.build_image_style_prompt(server_module.read_style_tokens_data())
    except Exception:
        fallback = ""
    if not image_style:
        return fallback

    lines = [
        "Project Profile 图片风格（优先级高于全局图片风格模板）：",
    ]
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
    if _project_reference_paths(project):
        lines.append("- 本项目已有 1-3 张项目级风格参考图；兼容模型会把这些 PNG 作为 reference images 一起提交。")
    lines.extend([
        "- 不可覆盖规则：visual_draft.png 外背景必须保持纯白 #FFFFFF。",
        "- 不可覆盖规则：最终视频背景不能画进生图。",
        "- 不可覆盖规则：所有语义元素必须留出明显白色间隔，不能重叠、粘连或穿插。",
    ])
    if fallback:
        lines.append("\n全局图片风格模板（仅作为 fallback，若与 Project Profile 冲突，以 Project Profile 为准）：")
        lines.append(fallback)
    return "\n".join(lines)


def _project_generate_prompt_for_slide(server_module: ModuleType, project: Any, slide: dict[str, Any], topic_name: str) -> str:
    style_prompt = _profile_style_prompt(project, server_module)
    slide_id = _safe_text(slide.get("slide_id"), 100)
    try:
        elements_str = "\n".join(server_module.compact_slide_element_lines(slide)) or "- 无可用视觉元素"
    except Exception:
        elements_str = "- 无可用视觉元素"
    return (
        "整体风格提示词：\n"
        f"{style_prompt}\n\n"
        "单页生图任务：\n"
        "- 生成一张 16:9 PPT 静态主图。\n"
        "- 背景必须是纯白 #FFFFFF，四条边和四个角保持连续纯白。\n"
        "- 如果请求附带项目级风格参考图，只把它作为整体风格、留白、层级、配色和密度参考；不要复制其中的具体内容。\n"
        "- 只根据下面的元素清单组织画面；不要加入 narration、讲稿、制作说明或额外页面。\n"
        "- 每个元素都要清晰分离，方便后续人工 Mask；元素之间不得重叠、穿插、压住或粘连。\n\n"
        f"Slide ID: {slide_id}\n"
        "元素清单（程序已从 Step 2B 精简）：\n"
        f"{elements_str}"
    )


def _can_send_project_references(server_module: ModuleType, model: str, base_url: str | None, reference_paths: list[str]) -> bool:
    if not reference_paths:
        return False
    try:
        if callable(getattr(server_module, "is_seedream_image_model", None)) and server_module.is_seedream_image_model(model, base_url):
            return False
    except Exception:
        return False
    return str(model or "").startswith("gpt-image")


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


def _install_step3_routes(server_module: ModuleType) -> None:
    app = server_module.app
    if getattr(app.state, STEP3_ROUTES_MARKER, False):
        return
    required = (
        "Form", "Depends", "get_db", "Project", "HTTPException", "FileResponse",
        "read_current_slide_ids_or_404", "get_setting", "get_openai_client",
        "enforce_white_generation_background", "generate_image_response",
        "extract_image_bytes_from_response", "process_and_save_image", "mark_slide_image_changed",
    )
    if not all(hasattr(server_module, name) for name in required):
        return

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
        save_path = _run_dir(project) / "slides" / slide_id / image_filename
        if not api_key:
            raise server_module.HTTPException(status_code=400, detail="未配置生图 API 密钥，请在系统设置中配置，或使用下方本地上传图片功能。")

        try:
            client = server_module.get_openai_client(api_key=api_key, base_url=base_url)
            image_size = server_module.get_setting("image_size", "1024x1024")
            effective_prompt = server_module.enforce_white_generation_background(prompt)
            response = None
            project_reference_paths = _project_reference_paths(project)
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
                            "Project style reference generation unavailable for %s, falling back to normal image generation: %s",
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
                    "used_project_style_references": bool(response is not None and project_reference_paths),
                }
            server_module.mark_slide_image_changed(project, slide_id, db)
            return {
                "success": True,
                "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}",
                "used_project_style_references": bool(project_reference_paths),
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


def _register(server_module: ModuleType) -> bool:
    if getattr(server_module, PATCH_MARKER, False):
        return True
    required = ("app", "Project", "HTTPException", "Depends", "get_db", "FileResponse")
    if not all(hasattr(server_module, name) for name in required):
        return False
    app = server_module.app

    def list_reference_images(project_id: str, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        return {"success": True, "references": _load_manifest(project, project_id)}

    def generate_reference_images(project_id: str, payload: dict[str, Any] | None = None, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        manifest = _generate_reference_images(server_module, project, project_id, payload if isinstance(payload, dict) else {})
        return {"success": True, "references": manifest}

    def get_reference_image(project_id: str, index: int, db: Any = server_module.Depends(server_module.get_db)) -> Any:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        if index < 1 or index > 3:
            raise server_module.HTTPException(status_code=404, detail="参考图不存在")
        path = _references_dir(project) / f"style_reference_{index:02d}.png"
        if not path.exists():
            raise server_module.HTTPException(status_code=404, detail="参考图不存在")
        return server_module.FileResponse(str(path), media_type="image/png")

    app.add_api_route("/api/projects/{project_id}/project-profile/image-style/reference-images", list_reference_images, methods=["GET"])
    app.add_api_route("/api/projects/{project_id}/project-profile/image-style/reference-images/generate", generate_reference_images, methods=["POST"])
    app.add_api_route("/api/projects/{project_id}/project-profile/image-style/reference-images/{index}", get_reference_image, methods=["GET"])
    try:
        _install_step3_routes(server_module)
    except Exception:
        pass
    setattr(server_module, PATCH_MARKER, True)
    return True


def _candidate_modules() -> list[ModuleType]:
    return [module for module in list(sys.modules.values()) if isinstance(module, ModuleType) and hasattr(module, "app") and hasattr(module, "Project")]


def _install_when_ready() -> None:
    def worker() -> None:
        while not os.environ.get("PPT_STUDIO_DISABLE_PROJECT_STYLE_REFERENCES"):
            for module in _candidate_modules():
                try:
                    if _register(module):
                        return
                except Exception:
                    return
            time.sleep(0.1)
    threading.Thread(name="ppt-project-style-references-runtime", target=worker, daemon=True).start()


_install_when_ready()
