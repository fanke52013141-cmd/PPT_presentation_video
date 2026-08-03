"""Step 3 prompt, generation, upload, ordering, and confirmation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Callable, Dict, List, Optional
import uuid

from fastapi import HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from artifact_fingerprint import sha256_file, sha256_json
from config_store import get_setting
from database import Project
from global_image_style_service import (
    active_style_reference_paths,
    build_image_style_prompt,
    read_style_tokens_data,
    should_send_style_reference_images,
)
import invalidation_service
from pipeline_lifecycle import write_json_atomic
from project_storage import slide_file as storage_slide_file
from project_style_reference_service import (
    can_send_project_references,
    profile_style_prompt,
    project_generate_prompt_for_slide,
    project_reference_paths,
)
from storyboard_service import read_prompt_template
from visual_contract_service import normalize_visual_type
from visual_provenance import (
    promote_candidate_provenance,
    provenance_path as visual_provenance_path,
    validate_visual_provenance_set,
    visual_provenance_status,
    write_visual_provenance,
)
from repository_paths import (
    REPO_ROOT,
    STEP3_IMAGE_PROMPT_TEMPLATE_PATH,
)


logger = logging.getLogger("PPTStudio.ImageWorkflow")
STEP3_IMAGE_PROMPTS_FILE = "step3_image_prompts.json"
MAX_IMAGE_UPLOAD_BYTES = int(
    os.environ.get(
        "PPT_STUDIO_MAX_IMAGE_UPLOAD_BYTES",
        str(20 * 1024 * 1024),
    )
)


def _not_configured(*_args: Any, **_kwargs: Any) -> Any:
    raise RuntimeError("Image workflow dependencies have not been configured")


all_current_slide_images_exist: Callable[..., Any] = _not_configured
current_slide_file_or_404: Callable[..., Any] = _not_configured
extract_image_bytes_from_response: Callable[..., Any] = _not_configured
generate_image_response: Callable[..., Any] = _not_configured
get_openai_client: Callable[..., Any] = _not_configured
handle_step_navigation: Callable[..., Any] = _not_configured
mark_slide_image_changed: Callable[..., Any] = _not_configured
process_and_save_image: Callable[..., Any] = _not_configured
read_current_slide_ids_or_404: Callable[..., Any] = _not_configured
read_json_file: Callable[..., Any] = _not_configured
refresh_reveal_semantic_blocks: Callable[..., Any] = _not_configured
reveal_lock_for: Callable[..., Any] = _not_configured
sync_reveal_manifest_to_contract: Callable[..., Any] = _not_configured
write_project_log: Callable[..., Any] = _not_configured


@dataclass(frozen=True)
class ImageWorkflowDependencies:
    all_current_slide_images_exist: Callable[..., Any]
    current_slide_file_or_404: Callable[..., Any]
    extract_image_bytes_from_response: Callable[..., Any]
    generate_image_response: Callable[..., Any]
    get_openai_client: Callable[..., Any]
    handle_step_navigation: Callable[..., Any]
    mark_slide_image_changed: Callable[..., Any]
    process_and_save_image: Callable[..., Any]
    read_current_slide_ids_or_404: Callable[..., Any]
    read_json_file: Callable[..., Any]
    refresh_reveal_semantic_blocks: Callable[..., Any]
    reveal_lock_for: Callable[..., Any]
    sync_reveal_manifest_to_contract: Callable[..., Any]
    write_project_log: Callable[..., Any]


def configure_image_workflow_dependencies(
    dependencies: ImageWorkflowDependencies,
) -> None:
    global all_current_slide_images_exist
    global current_slide_file_or_404
    global extract_image_bytes_from_response
    global generate_image_response
    global get_openai_client
    global handle_step_navigation
    global mark_slide_image_changed
    global process_and_save_image
    global read_current_slide_ids_or_404
    global read_json_file
    global refresh_reveal_semantic_blocks
    global reveal_lock_for
    global sync_reveal_manifest_to_contract
    global write_project_log
    all_current_slide_images_exist = dependencies.all_current_slide_images_exist
    current_slide_file_or_404 = dependencies.current_slide_file_or_404
    extract_image_bytes_from_response = dependencies.extract_image_bytes_from_response
    generate_image_response = dependencies.generate_image_response
    get_openai_client = dependencies.get_openai_client
    handle_step_navigation = dependencies.handle_step_navigation
    mark_slide_image_changed = dependencies.mark_slide_image_changed
    process_and_save_image = dependencies.process_and_save_image
    read_current_slide_ids_or_404 = dependencies.read_current_slide_ids_or_404
    read_json_file = dependencies.read_json_file
    refresh_reveal_semantic_blocks = dependencies.refresh_reveal_semantic_blocks
    reveal_lock_for = dependencies.reveal_lock_for
    sync_reveal_manifest_to_contract = dependencies.sync_reveal_manifest_to_contract
    write_project_log = dependencies.write_project_log


def step3_image_prompts_path(project: Project) -> str:
    return os.path.join(project.run_dir, "planning", STEP3_IMAGE_PROMPTS_FILE)


def default_step3_image_system_content() -> str:
    return read_prompt_template(STEP3_IMAGE_PROMPT_TEMPLATE_PATH)


def read_step3_image_system_content(project: Project) -> str:
    default_value = default_step3_image_system_content()
    stored = read_json_file(step3_image_prompts_path(project), {})
    if isinstance(stored, str):
        value = stored.strip()
    elif isinstance(stored, dict):
        value = str(stored.get("system_content") or "").strip()
    else:
        value = ""
    return value or default_value


def write_step3_image_system_content(project: Project, system_content: str) -> None:
    write_json_atomic(
        step3_image_prompts_path(project),
        {
            "version": "step3_image_prompt_settings_v1",
            "system_content": system_content,
        },
    )


def step3_image_input_contract() -> Dict[str, Any]:
    return {
        "slide_id": "仅用于区分任务，不会作为画面文字",
        "main_title": "唯一主标题，必须准确呈现",
        "body_elements": [
            {
                "type": "text 或 picture",
                "content": "必须呈现的正文文字，或必须落实的可视化描述",
            }
        ],
    }


def step3_image_input_example() -> Dict[str, Any]:
    return {
        "slide_id": "slide_003",
        "main_title": "为什么要拆分 Token？",
        "body_elements": [
            {"type": "picture", "content": "左侧展示一句中文被切分成彩色 Token 积木"},
            {"type": "text", "content": "模型按 Token 计算，而不是直接读取文字"},
        ],
    }


def step3_image_example_slide() -> Dict[str, Any]:
    example = step3_image_input_example()
    groups = []
    for item in example["body_elements"]:
        visual_type = str(item.get("type") or "picture")
        content = str(item.get("content") or "")
        groups.append(
            {
                "role": "content_body",
                "visual_type": visual_type,
                "display_text": content if visual_type == "text" else "",
                "visual_anchor": content,
            }
        )
    return {
        "slide_id": example["slide_id"],
        "main_title": example["main_title"],
        "visual_groups": groups,
    }


# 辅助生成某一页 PPT 生图的 Prompt。
def step3_slide_input_payload(slide: Dict[str, Any]) -> Dict[str, Any]:
    slide_id = str(slide.get("slide_id") or "").strip()
    main_title = str(slide.get("main_title") or "").strip()
    body_elements: List[Dict[str, str]] = []
    for group in slide.get("visual_groups", []) or []:
        if not isinstance(group, dict):
            continue
        role = str(group.get("role") or "content_body").strip().lower()
        if role == "title":
            continue
        visual_type = normalize_visual_type(
            group.get("visual_type"),
            has_text=bool(str(group.get("display_text") or "").strip()),
        )
        if visual_type == "text":
            content = str(
                group.get("display_text")
                or group.get("visible_text")
                or group.get("visual_anchor")
                or ""
            ).strip()
        else:
            content = str(
                group.get("visual_anchor")
                or group.get("mask_target")
                or group.get("visible_text")
                or ""
            ).strip()
        if content:
            body_elements.append({"type": visual_type, "content": content})
    return {
        "slide_id": slide_id,
        "main_title": main_title,
        "body_elements": body_elements,
    }


def compact_slide_element_lines(slide: Dict[str, Any]) -> List[str]:
    payload = step3_slide_input_payload(slide)
    return [
        f"- [{item['type']}] {item['content']}" for item in payload["body_elements"]
    ]


def build_step3_global_image_prompt(
    style_prompt: str, system_content: Optional[str] = None
) -> str:
    return (
        "=== 图片生成 System Content ===\n"
        f"{str(system_content or default_step3_image_system_content()).strip()}\n\n"
        "=== 当前生效的图片风格 ===\n"
        f"{str(style_prompt or '').strip()}"
    )


def build_step3_slide_specific_prompt(slide: Dict[str, Any]) -> str:
    return "最小单页输入（不要把字段名、类型名或 slide_id 画进页面）：\n" + json.dumps(
        step3_slide_input_payload(slide), ensure_ascii=False, indent=2
    )


def compose_step3_single_slide_prompt(
    style_prompt: str,
    slide: Dict[str, Any],
    system_content: Optional[str] = None,
) -> str:
    prompt = (
        f"{build_step3_global_image_prompt(style_prompt, system_content)}"
        f"\n\n=== 当前 Slide 输入 ===\n{build_step3_slide_specific_prompt(slide)}"
    )
    return enforce_white_generation_background(prompt)


def compose_step3_batch_copy_prompt(
    style_prompt: str,
    slides: List[Dict[str, Any]],
    system_content: Optional[str] = None,
) -> str:
    slide_sections = []
    for slide in slides:
        if not isinstance(slide, dict):
            continue
        slide_id = str(slide.get("slide_id") or "").strip() or "未命名"
        slide_sections.append(
            f"--- Slide {slide_id} ---\n{build_step3_slide_specific_prompt(slide)}"
        )
    prompt = (
        "请按以下统一要求，依次为每个 Slide 分别生成 1 张独立图片。\n"
        "先完整理解全局说明，再逐页读取具体内容；不要把多个 Slide 合并到一张图片中。\n\n"
        "=== 全局统一说明（仅出现一次） ===\n"
        f"{build_step3_global_image_prompt(style_prompt, system_content)}\n\n"
        "=== 各 Slide 具体内容 ===\n\n" + "\n\n".join(slide_sections)
    ).strip()
    return enforce_white_generation_background(prompt)


def step3_non_overridable_rules_prompt() -> str:
    return (
        "<NonOverridableProductionRules>\n"
        "这些生产铁律由系统强制追加：1920×1080、16:9；外围背景纯白 #FFFFFF；"
        "只保留一个主标题且不生成副标题；所有内容止于 y<930；y=930..1080 完全留空；"
        "独立语义元素不得重叠、穿插、压住或粘连，并保留可见纯白间隙。\n"
        "</NonOverridableProductionRules>"
    )


def enforce_white_generation_background(prompt: str) -> str:
    marker = "<NonOverridableProductionRules>"
    if marker in str(prompt or ""):
        return str(prompt or "").strip()
    return f"{prompt.strip()}\n\n{step3_non_overridable_rules_prompt()}".strip()


def step3_prompt_settings_response(project: Project) -> Dict[str, Any]:
    contract = read_json_file(
        os.path.join(project.run_dir, "planning", "visual_contract.json"), {}
    )
    slides = (
        contract.get("slides")
        if isinstance(contract, dict) and isinstance(contract.get("slides"), list)
        else []
    )
    first_slide = next((slide for slide in slides if isinstance(slide, dict)), None)
    system_content = read_step3_image_system_content(project)
    style_prompt = profile_style_prompt(project)
    return {
        "success": True,
        "prompts": {
            "system_content": system_content,
            "default_system_content": default_step3_image_system_content(),
            "current_input": step3_slide_input_payload(first_slide)
            if first_slide
            else step3_image_input_example(),
            "input_contract": step3_image_input_contract(),
            "input_example": step3_image_input_example(),
            "output_description": "一张完整的 1920×1080、16:9 PPT 位图；无文字说明、JSON、Mask 或备选拼图。",
            "style_content": style_prompt,
            "protected_rules": step3_non_overridable_rules_prompt(),
            "full_prompt_example": compose_step3_single_slide_prompt(
                style_prompt,
                first_slide or step3_image_example_slide(),
                system_content,
            ),
        },
    }


def get_step3_prompt_settings(project_id: str, db: Session):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return step3_prompt_settings_response(project)


def update_step3_prompt_settings(
    project_id: str,
    payload: Dict[str, Any],
    db: Session,
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    prompts = (
        payload.get("prompts") if isinstance(payload.get("prompts"), dict) else payload
    )
    system_content = str(prompts.get("system_content") or "").strip()
    if not system_content:
        raise HTTPException(status_code=400, detail="图片生成 System Content 不能为空")
    if len(system_content) > 40000:
        raise HTTPException(
            status_code=400, detail="图片生成 System Content 不能超过 40000 个字符"
        )
    write_step3_image_system_content(project, system_content)
    return step3_prompt_settings_response(project)


def get_slide_prompts(project_id: str, db: Session):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    if not os.path.exists(contract_path):
        raise HTTPException(status_code=400, detail="分镜规划尚未生成")

    with open(contract_path, "r", encoding="utf-8") as f:
        contract = json.load(f)

    # 单页生成仍返回完整 Prompt；网页端批量复制另用一份全局说明 + 每页差异内容。
    slide_prompts = []
    slides = [slide for slide in contract.get("slides", []) if isinstance(slide, dict)]
    topic = contract.get("topic") if isinstance(contract.get("topic"), dict) else {}
    topic_name = str(topic.get("topic_name") or project.name or "")
    style_prompt = profile_style_prompt(project)
    system_content = read_step3_image_system_content(project)
    for slide in slides:
        slide_id = slide["slide_id"]
        generated_prompt = project_generate_prompt_for_slide(project, slide, topic_name)
        slide_prompts.append(
            {
                "slide_id": slide_id,
                "title": slide["main_title"],
                "prompt": generated_prompt,
                "slide_prompt": build_step3_slide_specific_prompt(slide),
            }
        )

    return {
        "success": True,
        "prompts": slide_prompts,
        "global_prompt": enforce_white_generation_background(
            build_step3_global_image_prompt(style_prompt, system_content)
        ),
        "batch_prompt": compose_step3_batch_copy_prompt(
            style_prompt, slides, system_content
        ),
        "prompt_settings": {
            "system_content": system_content,
            "input_contract": step3_image_input_contract(),
            "input_example": step3_image_input_example(),
            "output_description": "一张完整的 1920×1080、16:9 PPT 位图。",
        },
    }


def generate_slide_image(
    project_id: str,
    slide_id: str,
    prompt: str,
    preview: bool,
    db: Session,
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    api_key = get_setting("image_api_key")
    base_url = get_setting("image_base_url")
    model = get_setting("image_model", "gpt-image-1")
    image_filename = "visual_candidate.png" if preview else "visual_draft.png"
    save_path = current_slide_file_or_404(project, slide_id, image_filename)

    if not api_key:
        raise HTTPException(
            status_code=400,
            detail="未配置生图 API 密钥，请在系统设置中配置，或使用下方本地上传图片功能。",
        )

    try:
        client = get_openai_client(api_key=api_key, base_url=base_url)
        image_size = get_setting("image_size", "1024x1024")
        effective_prompt = enforce_white_generation_background(prompt)
        logger.info(
            f"Generating image for {slide_id} using {model}, size={image_size}, prompt: {effective_prompt[:80]}"
        )

        response = None
        used_reference_paths: List[str] = []
        project_references = project_reference_paths(project)
        if project_references:
            reference_paths = project_references
            use_reference_images = can_send_project_references(
                model, base_url, reference_paths
            )
        else:
            style_tokens = read_style_tokens_data()
            reference_paths = active_style_reference_paths()
            use_reference_images = should_send_style_reference_images(
                model=model,
                base_url=base_url,
                reference_paths=reference_paths,
                style_tokens=style_tokens,
            )
        if reference_paths and not use_reference_images:
            logger.info(
                "Skipping binary style reference images for %s: active references are not compatible with current model/style.",
                slide_id,
            )
        if use_reference_images:
            reference_files = []
            try:
                reference_files = [open(path, "rb") for path in reference_paths]
                response = client.images.edit(
                    model=model,
                    image=reference_files,
                    prompt=effective_prompt,
                    size=image_size,
                    n=1,
                )
                used_reference_paths = list(reference_paths)
                logger.info(
                    "Image generation used %s style reference images.",
                    len(reference_files),
                )
            except Exception as reference_error:
                logger.warning(
                    "Reference image generation is unavailable, falling back to images.generate: %s",
                    reference_error,
                )
            finally:
                for reference_file in reference_files:
                    reference_file.close()

        if response is None:
            response = generate_image_response(
                client=client,
                model=model,
                prompt=effective_prompt,
                size=image_size,
                base_url=base_url,
            )

        # ── 兼容两种响应格式：URL 和 base64 (b64_json) ──
        img_bytes = extract_image_bytes_from_response(response)

        process_and_save_image(img_bytes, save_path)
        write_visual_provenance(
            project.run_dir,
            slide_id,
            image_path=save_path,
            provider="openai_compatible",
            source_type="api_generation",
            model=model,
            prompt=effective_prompt,
            reference_paths=used_reference_paths,
            source_bytes=img_bytes,
            candidate=preview,
        )
        logger.info(f"Image saved for {slide_id}: {save_path}")
        if preview:
            return {
                "success": True,
                "candidate_url": f"/api/projects/{project_id}/slides/{slide_id}/candidate?t={uuid.uuid4().hex[:6]}",
            }
        mark_slide_image_changed(project, slide_id, db)

        return {
            "success": True,
            "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}",
        }
    except Exception as e:
        logger.error(f"Image generation error for {slide_id}: {e}")
        raise HTTPException(status_code=500, detail=f"生成图片失败: {str(e)}")


def upload_slide_image(
    project_id: str,
    slide_id: str,
    file: UploadFile,
    db: Session,
):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    save_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    try:
        content = file.file.read(MAX_IMAGE_UPLOAD_BYTES + 1)
        if len(content) > MAX_IMAGE_UPLOAD_BYTES:
            raise ValueError(
                f"图片文件超过 {MAX_IMAGE_UPLOAD_BYTES // (1024 * 1024)} MB 限制"
            )
        process_and_save_image(content, save_path)
        write_visual_provenance(
            project.run_dir,
            slide_id,
            image_path=save_path,
            provider="manual_upload",
            source_type="local_upload",
            source_bytes=content,
            source_filename=str(file.filename or ""),
        )
        mark_slide_image_changed(project, slide_id, db)
        return {
            "success": True,
            "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.error(f"Upload image error for {slide_id}: {e}")
        raise HTTPException(status_code=500, detail=f"上传图片失败: {str(e)}")


# 获取指定页面的图片资源接口
def get_slide_image_file(project_id: str, slide_id: str, db: Session):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    img_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    if not os.path.exists(img_path):
        raise HTTPException(status_code=404, detail="图片不存在")

    return FileResponse(img_path, media_type="image/png")


def get_slide_candidate_file(project_id: str, slide_id: str, db: Session):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    candidate_path = current_slide_file_or_404(
        project, slide_id, "visual_candidate.png"
    )
    if not os.path.exists(candidate_path):
        raise HTTPException(status_code=404, detail="候选图片不存在")
    return FileResponse(candidate_path, media_type="image/png")


def apply_slide_candidate(project_id: str, payload: Dict[str, Any], db: Session):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    slide_id = str(payload.get("slide_id") or "").strip()
    candidate_path = current_slide_file_or_404(
        project, slide_id, "visual_candidate.png"
    )
    image_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    if not os.path.exists(candidate_path):
        raise HTTPException(status_code=404, detail="候选图片不存在，请先生成")

    os.replace(candidate_path, image_path)
    promote_candidate_provenance(project.run_dir, slide_id)
    mark_slide_image_changed(project, slide_id, db)
    return {
        "success": True,
        "image_url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:6]}",
    }


def delete_all_slide_images(project_id: str, db: Session):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    slide_ids = read_current_slide_ids_or_404(project)
    deleted_count = 0
    with reveal_lock_for(project):
        for slide_id in slide_ids:
            image_path = Path(
                storage_slide_file(project.run_dir, slide_id, "visual_draft.png")
            )
            candidate_path = Path(
                storage_slide_file(project.run_dir, slide_id, "visual_candidate.png")
            )
            if image_path.exists():
                image_path.unlink()
                deleted_count += 1
            for path in (
                candidate_path,
                visual_provenance_path(project.run_dir, slide_id),
                visual_provenance_path(project.run_dir, slide_id, candidate=True),
            ):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        invalidation_service.slide_images_changed(
            project,
            slide_ids,
            all_images_exist=False,
        )
        db.commit()
    return {"success": True, "deleted_count": deleted_count, "slide_ids": slide_ids}


def delete_slide_image(project_id: str, slide_id: str, db: Session):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    image_path = current_slide_file_or_404(project, slide_id, "visual_draft.png")
    candidate_path = current_slide_file_or_404(
        project, slide_id, "visual_candidate.png"
    )
    if not os.path.exists(image_path):
        raise HTTPException(status_code=404, detail="图片不存在")
    os.remove(image_path)
    if os.path.exists(candidate_path):
        os.remove(candidate_path)
    for candidate in (
        visual_provenance_path(project.run_dir, slide_id),
        visual_provenance_path(project.run_dir, slide_id, candidate=True),
    ):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
    mark_slide_image_changed(project, slide_id, db)
    return {"success": True, "slide_id": slide_id}


def get_all_images(project_id: str, db: Session):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    slides_dir = os.path.join(project.run_dir, "slides")
    contract_path = os.path.join(project.run_dir, "planning", "visual_contract.json")
    contract_slide_ids: List[str] = []
    if os.path.exists(contract_path):
        try:
            with open(contract_path, "r", encoding="utf-8") as f:
                contract = json.load(f)
            contract_slide_ids = [
                str(slide.get("slide_id", "")).strip()
                for slide in contract.get("slides", [])
                if isinstance(slide, dict) and str(slide.get("slide_id", "")).strip()
            ]
        except Exception as exc:
            logger.warning(
                f"Failed to read visual contract for image list filtering: {exc}"
            )
    results = []

    if contract_slide_ids:
        for slide_id in contract_slide_ids:
            img_file = os.path.join(slides_dir, slide_id, "visual_draft.png")
            exists = os.path.exists(img_file)
            results.append(
                {
                    "slide_id": slide_id,
                    "exists": exists,
                    "url": f"/api/projects/{project_id}/slides/{slide_id}/image?t={uuid.uuid4().hex[:4]}"
                    if exists
                    else None,
                    "provenance": visual_provenance_status(project.run_dir, slide_id)
                    if exists
                    else None,
                }
            )
    elif os.path.exists(slides_dir):
        # 扫描 slides 目录下的子目录，按名称字母排序
        for slide_dir_name in sorted(os.listdir(slides_dir)):
            slide_path = os.path.join(slides_dir, slide_dir_name)
            if os.path.isdir(slide_path):
                img_file = os.path.join(slide_path, "visual_draft.png")
                exists = os.path.exists(img_file)
                results.append(
                    {
                        "slide_id": slide_dir_name,
                        "exists": exists,
                        "url": f"/api/projects/{project_id}/slides/{slide_dir_name}/image?t={uuid.uuid4().hex[:4]}"
                        if exists
                        else None,
                        "provenance": visual_provenance_status(
                            project.run_dir, slide_dir_name
                        )
                        if exists
                        else None,
                    }
                )
    return {
        "success": True,
        "images": results,
        "order_version": step3_image_assignment_version(
            project.run_dir,
            [item["slide_id"] for item in results],
        ),
    }


def step3_image_assignment_version(run_dir: str, slide_ids: List[str]) -> str:
    """Fingerprint fixed storyboard slots and the image currently assigned to each slot."""
    root = Path(run_dir)
    return sha256_json(
        {
            "slots": [
                {
                    "slide_id": str(slide_id),
                    "image_sha256": sha256_file(
                        storage_slide_file(root, str(slide_id), "visual_draft.png")
                    ),
                    "provenance_sha256": sha256_file(
                        visual_provenance_path(root, str(slide_id))
                    ),
                }
                for slide_id in slide_ids
            ]
        }
    )


def _copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f"{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _restore_optional_file(snapshot: Optional[Path], destination: Path) -> None:
    if snapshot is not None and snapshot.exists():
        _copy_file_atomic(snapshot, destination)
        return
    try:
        destination.unlink()
    except FileNotFoundError:
        pass


def update_step3_image_order(project_id: str, payload: Dict[str, Any], db: Session):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from_index = payload.get("from_index")
    to_index = payload.get("to_index")
    if (
        isinstance(from_index, bool)
        or isinstance(to_index, bool)
        or not isinstance(from_index, int)
        or not isinstance(to_index, int)
    ):
        raise HTTPException(status_code=400, detail="from_index 和 to_index 必须是整数")

    expected_version = str(payload.get("order_version") or "").strip()
    if not expected_version:
        raise HTTPException(status_code=428, detail="缺少排序版本，请刷新页面后重试")

    slide_ids = read_current_slide_ids_or_404(project)
    if not (0 <= from_index < len(slide_ids) and 0 <= to_index < len(slide_ids)):
        raise HTTPException(status_code=400, detail="图片移动位置超出当前分镜范围")
    if from_index == to_index:
        return {
            "success": True,
            "slide_ids": slide_ids,
            "order_version": step3_image_assignment_version(project.run_dir, slide_ids),
        }

    root = Path(project.run_dir)
    with reveal_lock_for(project):
        current_version = step3_image_assignment_version(project.run_dir, slide_ids)
        if expected_version != current_version:
            raise HTTPException(
                status_code=409, detail="图片对应关系已被其他操作更新，请刷新后重试"
            )

        source_slide_id = slide_ids[from_index]
        source_image = Path(
            storage_slide_file(root, source_slide_id, "visual_draft.png")
        )
        if not source_image.exists():
            raise HTTPException(status_code=400, detail="被移动的位置没有图片")

        source_ids = list(slide_ids)
        moved_source_id = source_ids.pop(from_index)
        source_ids.insert(to_index, moved_source_id)
        affected_indexes = range(
            min(from_index, to_index), max(from_index, to_index) + 1
        )
        affected_slide_ids = [slide_ids[index] for index in affected_indexes]

        with tempfile.TemporaryDirectory(
            prefix="step3-image-move-", dir=root
        ) as temporary_value:
            snapshot_root = Path(temporary_value)
            for slide_id in affected_slide_ids:
                slide_snapshot = snapshot_root / slide_id
                slide_snapshot.mkdir(parents=True, exist_ok=True)
                image_path = Path(
                    storage_slide_file(root, slide_id, "visual_draft.png")
                )
                provenance_path = visual_provenance_path(root, slide_id)
                if image_path.exists():
                    shutil.copy2(image_path, slide_snapshot / "visual_draft.png")
                if provenance_path.exists():
                    shutil.copy2(
                        provenance_path, slide_snapshot / "visual_provenance.json"
                    )

            try:
                reassigned_at = datetime.now().isoformat(timespec="seconds")
                for index in affected_indexes:
                    target_slide_id = slide_ids[index]
                    assigned_source_id = source_ids[index]
                    source_snapshot = snapshot_root / assigned_source_id
                    target_dir = Path(
                        storage_slide_file(root, target_slide_id, "visual_draft.png")
                    ).parent
                    target_dir.mkdir(parents=True, exist_ok=True)
                    target_image = target_dir / "visual_draft.png"
                    target_provenance = visual_provenance_path(root, target_slide_id)

                    _restore_optional_file(
                        source_snapshot / "visual_draft.png", target_image
                    )
                    source_provenance_path = source_snapshot / "visual_provenance.json"
                    if source_provenance_path.exists() and target_image.exists():
                        try:
                            provenance = json.loads(
                                source_provenance_path.read_text(encoding="utf-8-sig")
                            )
                        except (OSError, json.JSONDecodeError):
                            provenance = None
                        if isinstance(provenance, dict):
                            history = provenance.get("assignment_history")
                            if not isinstance(history, list):
                                history = []
                            history.append(
                                {
                                    "from_slide_id": assigned_source_id,
                                    "to_slide_id": target_slide_id,
                                    "reassigned_at": reassigned_at,
                                }
                            )
                            provenance["assignment_history"] = history[-20:]
                            provenance["slide_id"] = target_slide_id
                            provenance["copied_to"] = (
                                f"slides/{target_slide_id}/visual_draft.png"
                            )
                            provenance["output_sha256"] = sha256_file(target_image)
                            write_json_atomic(target_provenance, provenance)
                        else:
                            _restore_optional_file(None, target_provenance)
                    else:
                        _restore_optional_file(None, target_provenance)
            except Exception:
                for slide_id in affected_slide_ids:
                    slide_snapshot = snapshot_root / slide_id
                    target_dir = Path(
                        storage_slide_file(root, slide_id, "visual_draft.png")
                    ).parent
                    _restore_optional_file(
                        slide_snapshot / "visual_draft.png",
                        target_dir / "visual_draft.png",
                    )
                    _restore_optional_file(
                        slide_snapshot / "visual_provenance.json",
                        visual_provenance_path(root, slide_id),
                    )
                raise

        for slide_id in affected_slide_ids:
            for candidate in (
                Path(storage_slide_file(root, slide_id, "visual_candidate.png")),
                visual_provenance_path(root, slide_id, candidate=True),
            ):
                try:
                    candidate.unlink()
                except FileNotFoundError:
                    pass
        invalidation_service.slide_images_changed(
            project,
            affected_slide_ids,
            all_images_exist=all_current_slide_images_exist(project),
        )
        db.commit()

    return {
        "success": True,
        "slide_ids": slide_ids,
        "order_version": step3_image_assignment_version(project.run_dir, slide_ids),
    }


def confirm_images(project_id: str, db: Session):
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    slide_ids = read_current_slide_ids_or_404(project)
    missing_images = [
        slide_id
        for slide_id in slide_ids
        if not os.path.exists(
            os.path.join(project.run_dir, "slides", slide_id, "visual_draft.png")
        )
    ]
    if missing_images:
        raise HTTPException(
            status_code=400, detail=f"以下页面还没有图片: {', '.join(missing_images)}"
        )
    provenance_errors = validate_visual_provenance_set(project.run_dir, slide_ids)
    if provenance_errors:
        details = ", ".join(
            f"{item['slide_id']}({item['reason']})" for item in provenance_errors
        )
        raise HTTPException(
            status_code=409,
            detail=f"以下页面图片来源缺失或已过期，请重新生成或上传: {details}",
        )

    # 步骤4：确认图片。将步骤 3 与 4 状态标记为已完成
    # 自动调用 write_reveal_manifest_template.py 生成 manifest 模板
    manifest_path = os.path.join(project.run_dir, "reveal_manifest.json")
    if not os.path.exists(manifest_path):
        template_script = os.path.abspath(
            os.path.join(
                os.path.dirname(__file__),
                "scripts",
                "write_reveal_manifest_template.py",
            )
        )
        res = subprocess.run(
            [sys.executable, template_script, "--run-dir", project.run_dir],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
        if res.returncode != 0:
            logger.error(f"Failed to write reveal manifest template: {res.stderr}")
            write_project_log(
                project,
                "step5_manifest_template_error",
                returncode=res.returncode,
                stdout=res.stdout.strip(),
                stderr=res.stderr.strip(),
            )
            raise HTTPException(
                status_code=500, detail="自动创建 Mask 标注文件失败，请确认分镜规划正常"
            )

        # Final rendering is manual-mask-only. Do not run historical box-fitting
        # algorithms during normal project initialization.
    sync_reveal_manifest_to_contract(project)
    refresh_reveal_semantic_blocks(project)

    handle_step_navigation(project, 4, db)
    return {"success": True}
