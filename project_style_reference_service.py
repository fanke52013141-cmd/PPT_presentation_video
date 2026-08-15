"""Step 3 image-style reference generation service.

This service turns Step 3 image-style ``sample_reference_image_prompts`` into 1-3
project-local PNG reference images. The generated images are stored under the
run's planning directory and tracked by planning/project_style_references.json.

The explicit router keeps legacy URLs as compatibility aliases.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from project_style_context import ProjectStyleDependencies

REFERENCE_DIRNAME = "style_references"
REFERENCE_MANIFEST = "project_style_references.json"
MANIFEST_VERSION = "step3_style_references_v1"
LEGACY_MANIFEST_VERSION = "project_style_references_v1"
REFERENCE_GENERATION_SYSTEM_CONTENT_KEY = "image_style_reference_generation_system_content"
DEFAULT_REFERENCE_GENERATION_SYSTEM_CONTENT = """<PromptVersion>image_style_reference_generation_v1_minimal</PromptVersion>

Generate one content-neutral PPT style reference image that demonstrates the supplied reusable style specification.

Use the scene brief only to provide enough neutral subject matter to reveal the style. Do not copy a real slide, brand, named character, watermark, or exact composition. Use only as many visual groups as the scene needs; one coherent group is valid. Keep the result clear enough to judge palette, line language, shapes, typography, composition, density, and iconography.

The reusable style specification and scene brief are supplied separately. Do not restate them as visible production notes. Output only the image."""
DEFAULT_REFERENCE_SCENE_BRIEFS = [
    "A cause-and-effect explainer with one central concept and supporting visual cues.",
    "A concise process explanation using clear symbols, labels, and directional relationships.",
    "A comparison page with two clearly differentiated ideas and one closing takeaway.",
]


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
    from step3_image_style_service import _step3_style

    return _step3_style(project)


def _reference_prompts(image_style: dict[str, Any], count: int) -> list[str]:
    prompts = image_style.get("sample_reference_image_prompts")
    if isinstance(prompts, list):
        result = [_safe_text(item, 4000) for item in prompts if _safe_text(item, 4000)]
    else:
        result = []
    for default_prompt in DEFAULT_REFERENCE_SCENE_BRIEFS:
        if len(result) >= count:
            break
        if default_prompt not in result:
            result.append(default_prompt)
    return result[:count]


def _read_reference_generation_system_content(
    dependencies: ProjectStyleDependencies,
) -> str:
    get_setting = dependencies.get_setting
    return _safe_text(
        get_setting(REFERENCE_GENERATION_SYSTEM_CONTENT_KEY, DEFAULT_REFERENCE_GENERATION_SYSTEM_CONTENT),
        30000,
    ) or DEFAULT_REFERENCE_GENERATION_SYSTEM_CONTENT


def _style_generation_prompt(
    raw_prompt: str,
    image_style: dict[str, Any],
    index: int,
    generation_system_content: str = DEFAULT_REFERENCE_GENERATION_SYSTEM_CONTENT,
) -> str:
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
            _safe_text(generation_system_content, 30000),
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
    from step3_image_style_service import _save_reference_images_to_step3_state

    _save_reference_images_to_step3_state(project, manifest)


def _generate_reference_images(
    dependencies: ProjectStyleDependencies,
    project: Any,
    project_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    image_style = _profile_image_style(project)
    if not image_style:
        raise dependencies.http_exception(status_code=400, detail="Step 3 当前图片风格为空，无法生成图片风格参考图")

    requested_count = _safe_count(payload.get("count") or image_style.get("reference_image_count_target") or 3)
    prompts = _reference_prompts(image_style, requested_count)
    if not prompts:
        raise dependencies.http_exception(status_code=400, detail="没有可用于生成 Step 3 图片风格参考图的 sample_reference_image_prompts")

    get_setting = dependencies.get_setting
    api_key = _safe_text(get_setting("image_api_key"), 4000)
    base_url = _safe_text(get_setting("image_base_url"), 1000) or None
    model = _safe_text(get_setting("image_model", "gpt-image-1"), 200) or "gpt-image-1"
    image_size = _safe_text(get_setting("image_size", "1024x1024"), 100) or "1024x1024"
    if not api_key:
        raise dependencies.http_exception(status_code=400, detail="未配置生图 API 密钥，请先在系统设置中配置")

    client = dependencies.get_openai_client(api_key=api_key, base_url=base_url, timeout=180.0, max_retries=0)
    references_dir = _references_dir(project)
    references_dir.mkdir(parents=True, exist_ok=True)

    generated = []
    generation_system_content = _read_reference_generation_system_content(dependencies)
    for index, raw_prompt in enumerate(prompts, start=1):
        final_prompt = _style_generation_prompt(
            raw_prompt,
            image_style,
            index,
            generation_system_content,
        )
        response = dependencies.generate_image_response(
            client=client,
            model=model,
            prompt=final_prompt,
            size=image_size,
            base_url=base_url,
        )
        img_bytes = dependencies.extract_image_bytes_from_response(response)
        filename = f"style_reference_{index:02d}.png"
        save_path = references_dir / filename
        dependencies.process_and_save_image(img_bytes, str(save_path))
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
        dependencies.write_project_log(
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


def _profile_style_prompt(
    project: Any,
    dependencies: ProjectStyleDependencies,
) -> str:
    image_style = _profile_image_style(project)
    fallback = ""
    try:
        fallback = dependencies.build_image_style_prompt(
            dependencies.read_style_tokens_data()
        )
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


def _project_generate_prompt_for_slide(
    dependencies: ProjectStyleDependencies,
    project: Any,
    slide: dict[str, Any],
    topic_name: str,
    ip_prompt_segment: str = "",
) -> str:
    style_prompt = _profile_style_prompt(project, dependencies)
    try:
        system_content = dependencies.read_step3_image_system_content(project)
        return dependencies.compose_step3_single_slide_prompt(
            style_prompt,
            slide,
            system_content,
            ip_prompt_segment,
        )
    except Exception:
        return _legacy_project_generate_prompt_for_slide(
            dependencies,
            project,
            slide,
            ip_prompt_segment,
        )


def _legacy_project_generate_prompt_for_slide(
    dependencies: ProjectStyleDependencies,
    project: Any,
    slide: dict[str, Any],
    ip_prompt_segment: str = "",
) -> str:
    style_prompt = _profile_style_prompt(project, dependencies)
    slide_id = _safe_text(slide.get("slide_id"), 100)
    elements_str = "- 无可用视觉元素"
    try:
        elements_str = "\n".join(
            dependencies.compact_slide_element_lines(slide)
        ) or elements_str
    except Exception:
        pass
    prompt = (
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
    if ip_prompt_segment:
        prompt = prompt + "\n\n" + ip_prompt_segment
    return prompt


def _can_send_project_references(
    dependencies: ProjectStyleDependencies,
    model: str,
    base_url: str | None,
    reference_paths: list[str],
) -> bool:
    if not reference_paths:
        return False
    try:
        if dependencies.is_seedream_image_model(model, base_url):
            return False
    except Exception:
        return False
    return str(model or "").startswith("gpt-image")


def project_reference_paths(project: Any) -> list[str]:
    return _project_reference_paths(project)


def profile_style_prompt(
    project: Any,
    dependencies: ProjectStyleDependencies | None = None,
) -> str:
    if dependencies is None:
        from project_style_context import get_project_style_context

        dependencies = get_project_style_context()
    return _profile_style_prompt(project, dependencies)


def project_generate_prompt_for_slide(
    project: Any,
    slide: dict[str, Any],
    topic_name: str,
    dependencies: ProjectStyleDependencies | None = None,
    ip_prompt_segment: str = "",
) -> str:
    if dependencies is None:
        from project_style_context import get_project_style_context

        dependencies = get_project_style_context()
    return _project_generate_prompt_for_slide(
        dependencies, project, slide, topic_name, ip_prompt_segment
    )


def can_send_project_references(
    model: str,
    base_url: str | None,
    reference_paths: list[str],
    dependencies: ProjectStyleDependencies | None = None,
) -> bool:
    if dependencies is None:
        from project_style_context import get_project_style_context

        dependencies = get_project_style_context()
    return _can_send_project_references(dependencies, model, base_url, reference_paths)


