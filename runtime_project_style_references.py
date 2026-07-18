"""Step 3 image style reference generation APIs.

This bridge turns Step 3 image-style ``sample_reference_image_prompts`` into 1-3
project-local PNG reference images. The generated images are stored under the
run's planning directory and tracked by planning/project_style_references.json.

The legacy /project-profile/image-style/reference-images routes are kept for
compatibility. New UI should call the Step 3 aliases exposed by
``runtime_step3_image_style.py``.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

PATCH_MARKER = "__ppt_project_style_references_patch__"
REFERENCE_DIRNAME = "style_references"
REFERENCE_MANIFEST = "project_style_references.json"
MANIFEST_VERSION = "step3_style_references_v1"
LEGACY_MANIFEST_VERSION = "project_style_references_v1"


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


def _safe_child_path(base: Path, filename: Any) -> Path | None:
    name = Path(_safe_text(filename, 200)).name
    if not name:
        return None
    candidate = (base / name).resolve()
    base_resolved = base.resolve()
    try:
        candidate.relative_to(base_resolved)
    except ValueError:
        return None
    return candidate


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
        result = [
            "A cause-and-effect explainer with one central concept and supporting visual cues.",
            "A concise process explanation using clear symbols, labels, and directional relationships.",
            "A comparison page with two clearly differentiated ideas and one closing takeaway.",
        ]
    return result[:count]


def _style_generation_prompt(raw_prompt: str, image_style: dict[str, Any], index: int) -> str:
    style_name = _safe_text(image_style.get("style_name"), 120)
    style_summary = _safe_text(image_style.get("style_summary"), 1000)
    system_content = _safe_text(image_style.get("system_content"), 5000)
    negative_rules = image_style.get("negative_prompt_rules") if isinstance(image_style.get("negative_prompt_rules"), list) else []
    if system_content:
        style_specification = system_content
    else:
        style_specification = "\n".join(part for part in [style_name, style_summary] if part)
    scene_brief = _safe_text(raw_prompt, 4000)
    if scene_brief == system_content:
        scene_brief = ""
    unique_negative_rules = [
        str(rule).strip()
        for rule in negative_rules
        if str(rule).strip() and str(rule).strip() not in style_specification
    ]
    return "\n".join(
        part
        for part in [
            f"Generate Step 3 image style reference #{index}.",
            "Reusable style specification:",
            style_specification,
            "Content-neutral scene brief:\n" + scene_brief if scene_brief else "",
            "Non-overridable production constraints:",
            "- 16:9 PPT-style image, centered composition, clean readable layout.",
            "- Entire outer canvas must be flat pure-white #FFFFFF; all four edges and corners stay continuously white.",
            "- Do not draw final-video background colors, background images, texture paper, gradients, shadows, vignettes, or noise into the outer canvas.",
            "- Use only as many semantic visual groups as the scene needs; one coherent group is valid.",
            "- No overlap, no touching, no sticking between text, icons, arrows, labels, borders, formulas, people, or decorative marks.",
            "Style-specific negative rules:\n" + "\n".join(f"- {rule}" for rule in unique_negative_rules) if unique_negative_rules else "",
            "Only output the image. Do not add production notes or UI elements.",
        ]
        if str(part).strip()
    )


def _image_url(project_id: str, index: int) -> str:
    # Legacy route kept for compatibility. Step 3 aliases rewrite this URL for the UI.
    return f"/api/projects/{project_id}/project-profile/image-style/reference-images/{index}?t={uuid.uuid4().hex[:8]}"


def _load_manifest(project: Any, project_id: str) -> dict[str, Any]:
    manifest = _read_json(_manifest_path(project), {})
    if not isinstance(manifest, dict):
        manifest = {}
    images = manifest.get("images") if isinstance(manifest.get("images"), list) else []
    normalized = []
    refs_dir = _references_dir(project)
    for item in images:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except Exception:
            continue
        path = _safe_child_path(refs_dir, item.get("filename"))
        if path is None or not path.exists():
            continue
        normalized.append({
            **item,
            "index": index,
            "filename": path.name,
            "url": _image_url(project_id, index),
        })
    return {
        "version": _safe_text(manifest.get("version")) or MANIFEST_VERSION,
        "legacy_version": LEGACY_MANIFEST_VERSION,
        "scope": "step3_image_style",
        "deprecated_route": True,
        "preferred_route": f"/api/projects/{project_id}/steps/3/image-style/reference-images",
        "updated_at": _safe_text(manifest.get("updated_at")),
        "style_name": _safe_text(manifest.get("style_name"), 120),
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
            path = _safe_child_path(refs_dir, item.get("filename"))
            if path is not None:
                candidates.append(path)
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
    # Legacy fallback only. runtime_step3_image_style_state patches this function
    # during normal startup so new flows write reference_images into
    # planning/step3_image_style.json instead.
    companion_path = _run_dir(project) / "planning" / "project_profile_prompt_companion.json"
    companion = _read_json(companion_path, {})
    if not isinstance(companion, dict):
        companion = {}
    companion["legacy_compatibility_only"] = True
    companion["preferred_state_file"] = "planning/step3_image_style.json"
    companion["style_reference_images"] = manifest.get("images", [])
    _write_json(companion_path, companion)


def _generate_reference_images(server_module: ModuleType, project: Any, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    image_style = _profile_image_style(project)
    if not image_style:
        raise server_module.HTTPException(status_code=400, detail="Step 3 当前图片风格为空，无法生成图片风格参考图")

    requested_count = _safe_count(payload.get("count") or image_style.get("reference_image_count_target") or 3)
    prompts = _reference_prompts(image_style, requested_count)
    if not prompts:
        raise server_module.HTTPException(status_code=400, detail="没有可用于生成 Step 3 图片风格参考图的 sample_reference_image_prompts")

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
        "version": MANIFEST_VERSION,
        "legacy_version": LEGACY_MANIFEST_VERSION,
        "scope": "step3_image_style",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "style_name": _safe_text(image_style.get("style_name"), 120),
        "images": generated,
    }
    _write_json(_manifest_path(project), manifest)
    _update_prompt_companion(project, manifest)
    try:
        server_module.write_project_log(
            project,
            "step3_style_reference_images_generated",
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

    lines = ["Step 3 当前图片风格（优先级高于全局默认图片风格）："]
    system_content = _safe_text(image_style.get("system_content"), 12000)
    if system_content:
        lines.append(system_content)
    else:
        for label, key in [("风格名称", "style_name"), ("风格摘要", "style_summary")]:
            value = _safe_text(image_style.get(key), 2000)
            if value:
                lines.append(f"- {label}: {value}")
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
    custom_requirement = _safe_text(image_style.get("custom_requirement"), 2000)
    if custom_requirement:
        lines.append(f"- 用户补充要求: {custom_requirement}")
    if _project_reference_paths(project):
        lines.append("- 已附带当前项目的图片风格参考图；只参考风格，不复制具体内容。")
    return "\n".join(lines)


def _project_generate_prompt_for_slide(server_module: ModuleType, project: Any, slide: dict[str, Any], topic_name: str) -> str:
    style_prompt = _profile_style_prompt(project, server_module)
    compose_prompt = getattr(server_module, "compose_step3_single_slide_prompt", None)
    if callable(compose_prompt):
        prompt_reader = getattr(server_module, "read_step3_image_system_content", None)
        system_content = prompt_reader(project) if callable(prompt_reader) else None
        return compose_prompt(style_prompt, slide, system_content)
    slide_id = _safe_text(slide.get("slide_id"), 100)
    elements_str = "- 无可用视觉元素"
    if callable(getattr(server_module, "compact_slide_element_lines", None)):
        try:
            elements_str = "\n".join(server_module.compact_slide_element_lines(slide)) or elements_str
        except Exception:
            pass
    return (
        "整体风格提示词：\n"
        f"{style_prompt}\n\n"
        "单页生图任务：\n"
        "- 生成一张 16:9 PPT 静态主图。\n"
        "- 背景必须是纯白 #FFFFFF，四条边和四个角保持连续纯白。\n"
        "- 如果请求附带 Step 3 图片风格参考图，只把它作为整体风格、留白、层级、配色和密度参考；不要复制其中的具体内容。\n"
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


# Source-owned Step 3 routes use these stable service wrappers. They resolve
# the underlying function at call time so the remaining style-state adapter can
# replace its data source without shadowing the HTTP routes.
def project_reference_paths(project: Any) -> list[str]:
    return _project_reference_paths(project)


def profile_style_prompt(project: Any, server_module: ModuleType) -> str:
    return _profile_style_prompt(project, server_module)


def project_generate_prompt_for_slide(
    server_module: ModuleType,
    project: Any,
    slide: dict[str, Any],
    topic_name: str,
) -> str:
    return _project_generate_prompt_for_slide(server_module, project, slide, topic_name)


def can_send_project_references(
    server_module: ModuleType,
    model: str,
    base_url: str | None,
    reference_paths: list[str],
) -> bool:
    return _can_send_project_references(server_module, model, base_url, reference_paths)


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
        return {
            "success": True,
            "references": _load_manifest(project, project_id),
            "deprecated_route": True,
            "preferred_route": f"/api/projects/{project_id}/steps/3/image-style/reference-images",
        }

    def generate_reference_images(project_id: str, payload: dict[str, Any] | None = None, db: Any = server_module.Depends(server_module.get_db)) -> dict[str, Any]:
        project = db.query(server_module.Project).filter(server_module.Project.id == project_id).first()
        if not project:
            raise server_module.HTTPException(status_code=404, detail="项目不存在")
        manifest = _generate_reference_images(server_module, project, project_id, payload if isinstance(payload, dict) else {})
        return {
            "success": True,
            "references": manifest,
            "deprecated_route": True,
            "preferred_route": f"/api/projects/{project_id}/steps/3/image-style/reference-images/generate",
        }

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
    setattr(server_module, PATCH_MARKER, True)
    return True
