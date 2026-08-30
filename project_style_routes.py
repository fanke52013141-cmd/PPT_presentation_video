"""Explicit FastAPI routes for Project Profile and Step 3 image style."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import shutil
import time
from typing import Any
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import yaml

from canvas_profile_service import get_project_canvas
from database import Project, get_db
import image_style_reverse_service as reverse_service
import project_profile_service
import project_profile_store
from project_style_context import (
    ProjectStyleDependencies,
    get_project_style_context,
)
import project_style_reference_service as reference_service
import project_style_reference_store as reference_store
import project_style_template_service as template_service
import step3_image_style_service as style_service


router = APIRouter()

# 单张风格参考图上限（与 storyboard_background / image_style_reverse 的 12MB 标准一致）
MAX_REFERENCE_IMAGE_BYTES = 12 * 1024 * 1024

AUTOMATION_MODES = [
    {"id": "manual_review", "name": "手动审核模式", "description": "按原流程逐步生成、检查和确认。"},
    {"id": "auto", "name": "全自动模式", "description": "配合一键生成运行完整链路；失败时暂停给用户处理。"},
]


def _context() -> ProjectStyleDependencies:
    return get_project_style_context()


from project_path_service import project_or_404 as _project_or_404


def _log(project: Project, event: str, **fields: Any) -> None:
    try:
        _context().write_project_log(project, event, **fields)
    except Exception:
        pass


@router.get("/api/project-profile/templates")
def get_project_profile_templates() -> dict[str, Any]:
    return {
        "success": True,
        "automation_modes": AUTOMATION_MODES,
        "storyboard_templates": [],
        "image_style_templates": [],
        "note": "Creation only exposes automation mode. Step 2 owns storyboard style; Step 3 owns image style.",
    }


@router.get("/api/projects/{project_id}/project-profile")
def get_project_profile(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    profile = project_profile_store.load_profile(project)
    return {"success": True, "profile": profile}


@router.api_route(
    "/api/projects/{project_id}/project-profile",
    methods=["PUT", "POST"],
)
def save_project_profile(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    try:
        profile = project_profile_store.save_profile(
            project,
            payload if isinstance(payload, dict) else {},
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _log(project, "project_profile_saved_lightweight", profile=profile)
    return {"success": True, "profile": profile}


@router.post("/api/project-profile/image-style/generate")
def generate_project_image_style(payload: dict[str, Any]) -> dict[str, Any]:
    style = project_profile_service.generate_image_style_with_llm(
        _context(),
        payload if isinstance(payload, dict) else {},
    )
    return {"success": True, "style": style}


@router.get("/api/settings/image-style-reverse")
def get_reverse_style_prompt_settings() -> dict[str, Any]:
    system_content, output_example = reverse_service.read_reverse_style_prompts(
        _context()
    )
    return {
        "success": True,
        "prompts": {
            "system_content": system_content,
            "output_example": output_example,
            "full_prompt": reverse_service.compose_reverse_style_prompt(
                system_content,
                output_example,
            ),
        },
        "defaults": {
            "system_content": reverse_service.DEFAULT_REVERSE_SYSTEM_CONTENT,
            "output_example": reverse_service.DEFAULT_REVERSE_OUTPUT_EXAMPLE,
        },
    }


@router.put("/api/settings/image-style-reverse")
def update_reverse_style_prompt_settings(
    payload: dict[str, Any],
) -> dict[str, Any]:
    prompts = payload.get("prompts") if isinstance(payload.get("prompts"), dict) else payload
    system_content = reverse_service.safe_text(prompts.get("system_content"), 30000)
    output_example = reverse_service.safe_text(prompts.get("output_example"), 20000)
    if not system_content or not output_example:
        raise HTTPException(
            status_code=400,
            detail="图片风格反推的 System Content 和 Output Example 不能为空",
        )
    _context().update_settings({
        reverse_service.REVERSE_SYSTEM_CONTENT_KEY: system_content,
        reverse_service.REVERSE_OUTPUT_EXAMPLE_KEY: output_example,
    })
    return {
        "success": True,
        "prompts": {
            "system_content": system_content,
            "output_example": output_example,
            "full_prompt": reverse_service.compose_reverse_style_prompt(
                system_content,
                output_example,
            ),
        },
    }


async def _reverse_style(
    project: Project,
    files: list[UploadFile],
    requirement: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    context = _context()
    saved = reverse_service.save_uploaded_references(context, project, files)
    requirement_text = reverse_service.safe_text(requirement, 4000)
    raw_style = reverse_service.call_vision_model(
        context,
        saved,
        project,
        requirement_text,
    )
    style = reverse_service.style_with_required_rules(
        raw_style,
        saved,
        requirement_text,
    )
    return saved, style


@router.post("/api/projects/{project_id}/steps/3/image-style/reverse")
async def reverse_step3_image_style(
    project_id: str,
    files: list[UploadFile] = File(...),
    requirement: str = Form(""),
    apply: bool = Form(True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    saved, style = await _reverse_style(project, files, requirement)
    state = (
        style_service.save_step3_style(
            project,
            style,
            "image_reverse_engineered",
        )
        if apply
        else {}
    )
    _log(
        project,
        "step3_image_style_saved",
        style_name=style.get("style_name"),
        path=str(style_service.state_path(project)),
    )
    return {
        "success": True,
        "style": style,
        "style_state": state,
        "inputs": saved,
    }


@router.post("/api/projects/{project_id}/project-profile/image-style/reverse")
async def reverse_legacy_project_image_style(
    project_id: str,
    files: list[UploadFile] = File(...),
    requirement: str = Form(""),
    apply: bool = Form(True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    saved, style = await _reverse_style(project, files, requirement)
    legacy_profile = (
        reverse_service.apply_style_to_project(project, style) if apply else None
    )
    preferred_route = f"/api/projects/{project_id}/steps/3/image-style/reverse"
    _log(
        project,
        "legacy_image_style_reverse_engineered",
        reference_count=len(saved),
        applied=bool(apply),
        style_name=style.get("style_name"),
        preferred_route=preferred_route,
    )
    return {
        "success": True,
        "style": style,
        "style_state": None,
        "legacy_profile": legacy_profile,
        "profile": legacy_profile,
        "inputs": saved,
        "deprecated_route": True,
        "preferred_route": preferred_route,
    }


@router.get("/api/projects/{project_id}/steps/3/image-style")
def get_step3_image_style(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    return {
        "success": True,
        "style_state": style_service.step3_style_state(project),
        "style": style_service.step3_style(project),
    }


@router.put("/api/projects/{project_id}/steps/3/image-style")
def put_step3_image_style(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    style = style_service.manual_style_from_payload(
        payload if isinstance(payload, dict) else {},
        style_service.step3_style(project),
    )
    if not style_service.safe_text(style.get("system_content"), 12000):
        raise HTTPException(
            status_code=400,
            detail="图片生成 System Content 不能为空",
        )
    state = style_service.save_step3_style(
        project,
        style,
        "manual_system_content",
    )
    _log(
        project,
        "step3_image_style_manual_saved",
        path=str(style_service.state_path(project)),
    )
    return {"success": True, "style": style, "style_state": state}


@router.get("/api/settings/image-style-reference-generation")
def get_reference_generation_prompt_settings() -> dict[str, Any]:
    system_content = reference_service.read_reference_generation_system_content(
        _context()
    )
    preview = reference_service.style_generation_prompt(
        reference_service.DEFAULT_REFERENCE_SCENE_BRIEFS[0],
        {
            "style_name": "示例图片风格",
            "system_content": "示例可复用视觉风格 System Content。",
            "negative_prompt_rules": ["avoid ornate frames"],
        },
        1,
        system_content,
    )
    return {
        "success": True,
        "prompts": {
            "system_content": system_content,
            "full_prompt_example": preview,
        },
        "defaults": {
            "system_content": reference_service.DEFAULT_REFERENCE_GENERATION_SYSTEM_CONTENT
        },
    }


@router.put("/api/settings/image-style-reference-generation")
def update_reference_generation_prompt_settings(
    payload: dict[str, Any],
) -> dict[str, Any]:
    prompts = payload.get("prompts") if isinstance(payload.get("prompts"), dict) else payload
    system_content = reference_service.safe_text(
        prompts.get("system_content"),
        30000,
    )
    if not system_content:
        raise HTTPException(
            status_code=400,
            detail="预览图生成 System Content 不能为空",
        )
    _context().update_settings({
        reference_service.REFERENCE_GENERATION_SYSTEM_CONTENT_KEY: system_content
    })
    return {"success": True, "prompts": {"system_content": system_content}}


def _step3_references(project: Project, project_id: str) -> dict[str, Any]:
    return template_service.rewrite_reference_urls(
        reference_service.load_manifest(project, project_id),
        project_id,
    )


@router.get("/api/projects/{project_id}/steps/3/image-style/reference-images")
def list_step3_reference_images(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    return {"success": True, "references": _step3_references(project, project_id)}


@router.post("/api/projects/{project_id}/steps/3/image-style/reference-images/generate")
def generate_step3_reference_images(
    project_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    manifest = reference_service.generate_reference_images(
        _context(),
        project,
        project_id,
        payload if isinstance(payload, dict) else {},
    )
    return {
        "success": True,
        "references": template_service.rewrite_reference_urls(
            manifest,
            project_id,
        ),
    }


@router.post("/api/projects/{project_id}/steps/3/image-style/reference-images")
async def upload_step3_reference_images(
    project_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    selected = [file for file in (files or []) if file is not None]
    if not selected:
        raise HTTPException(status_code=400, detail="请上传 1-3 张参考图")
    if len(selected) > 3:
        raise HTTPException(status_code=400, detail="最多只能上传 3 张参考图")
    refs_dir = reference_service.references_dir(project)
    refs_dir.mkdir(parents=True, exist_ok=True)
    canvas = get_project_canvas(project)
    uploaded: list[dict[str, Any]] = []
    for index, file in enumerate(selected, start=1):
        content_type = str(file.content_type or "").lower()
        if content_type and not content_type.startswith("image/"):
            raise HTTPException(
                status_code=415,
                detail=f"参考图 {index} 必须是图片文件",
            )
        content = await file.read(MAX_REFERENCE_IMAGE_BYTES + 1)
        if not content:
            continue
        if len(content) > MAX_REFERENCE_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"参考图 {index} 超过 12MB，请压缩后再上传",
            )
        filename = f"style_reference_{index:02d}.png"
        _context().process_and_save_image(
            content,
            str(refs_dir / filename),
            target_width=canvas["width"],
            target_height=canvas["height"],
        )
        uploaded.append({
            "index": index,
            "filename": filename,
            "prompt": f"手动上传参考图：{Path(str(file.filename or filename)).name}",
            "source": "manual_upload",
            "uploaded_at": datetime.now().isoformat(timespec="seconds"),
            "url": f"/api/projects/{project_id}/steps/3/image-style/reference-images/{index}?t={int(time.time())}",
        })
    if not uploaded:
        raise HTTPException(status_code=400, detail="参考图文件为空")
    manifest = {
        "version": "step3_style_references_v1",
        "legacy_version": "project_style_references_v1",
        "scope": "step3_image_style",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "style_name": "手动上传参考图",
        "images": uploaded,
    }
    reference_store.write_normalized_manifest(project, manifest)
    _log(
        project,
        "step3_image_style_reference_images_uploaded",
        count=len(uploaded),
    )
    return {"success": True, "references": _step3_references(project, project_id)}


@router.get("/api/projects/{project_id}/steps/3/image-style/reference-images/{index}")
def get_step3_reference_image(
    project_id: str,
    index: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    project = _project_or_404(db, project_id)
    if index < 1 or index > 3:
        raise HTTPException(status_code=404, detail="参考图不存在")
    root = reference_service.references_dir(project).resolve()
    path = (root / f"style_reference_{index:02d}.png").resolve()
    if path.parent != root or not path.is_file():
        raise HTTPException(status_code=404, detail="参考图不存在")
    return FileResponse(str(path), media_type="image/png")


@router.delete("/api/projects/{project_id}/steps/3/image-style/reference-images/{index}")
def delete_step3_reference_image(
    project_id: str,
    index: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    try:
        references = reference_store.delete_reference(project, project_id, index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _log(project, "step3_image_style_reference_image_deleted", index=index)
    return {
        "success": True,
        "references": template_service.rewrite_reference_urls(
            references,
            project_id,
        ),
    }


@router.delete("/api/projects/{project_id}/steps/3/image-style/reference-images")
def delete_all_step3_reference_images(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    references = reference_store.delete_all_references(project, project_id)
    _log(
        project,
        "step3_image_style_reference_images_deleted",
        count=references.get("deleted_count", 0),
    )
    return {
        "success": True,
        "references": template_service.rewrite_reference_urls(
            references,
            project_id,
        ),
    }


@router.get("/api/projects/{project_id}/project-profile/image-style/reference-images")
def list_legacy_reference_images(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    return {
        "success": True,
        "references": reference_service.load_manifest(project, project_id),
        "deprecated_route": True,
        "preferred_route": f"/api/projects/{project_id}/steps/3/image-style/reference-images",
    }


@router.post("/api/projects/{project_id}/project-profile/image-style/reference-images/generate")
def generate_legacy_reference_images(
    project_id: str,
    payload: dict[str, Any] | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    manifest = reference_service.generate_reference_images(
        _context(),
        project,
        project_id,
        payload if isinstance(payload, dict) else {},
    )
    return {
        "success": True,
        "references": manifest,
        "deprecated_route": True,
        "preferred_route": f"/api/projects/{project_id}/steps/3/image-style/reference-images/generate",
    }


@router.get("/api/projects/{project_id}/project-profile/image-style/reference-images/{index}")
def get_legacy_reference_image(
    project_id: str,
    index: int,
    db: Session = Depends(get_db),
) -> FileResponse:
    return get_step3_reference_image(project_id, index, db)


@router.delete("/api/projects/{project_id}/project-profile/image-style/reference-images/{index}")
def delete_legacy_reference_image(
    project_id: str,
    index: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = delete_step3_reference_image(project_id, index, db)
    result.update({
        "deprecated_route": True,
        "preferred_route": f"/api/projects/{project_id}/steps/3/image-style/reference-images/{index}",
    })
    return result


@router.delete("/api/projects/{project_id}/project-profile/image-style/reference-images")
def delete_all_legacy_reference_images(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    result = delete_all_step3_reference_images(project_id, db)
    result.update({
        "deprecated_route": True,
        "preferred_route": f"/api/projects/{project_id}/steps/3/image-style/reference-images",
    })
    return result


# 命名图片风格模板库的业务逻辑已迁至 project_style_template_service.py（审查 M-06）；
# 路由仅保留 HTTP 壳与响应组装。


@router.get("/api/image-style/project-templates")
def list_step3_templates() -> dict[str, Any]:
    _, paths = template_service.builtin_sources(_context())
    built_in = {
        "id": template_service.BUILTIN_HANDDRAWN_TEMPLATE_ID,
        "name": template_service.BUILTIN_HANDDRAWN_TEMPLATE_NAME,
        "built_in": True,
        "reference_count": min(3, len(paths)),
    }
    return {"success": True, "templates": [built_in, *template_service.read_templates(_context())]}


@router.get("/api/image-style/project-templates/{template_id}")
def get_step3_template_detail(template_id: str) -> dict[str, Any]:
    return template_service.template_detail(_context(), template_id)


@router.get("/api/image-style/project-templates/{template_id}/reference-images/{index}")
def get_step3_template_reference(
    template_id: str,
    index: int,
) -> FileResponse:
    context = _context()
    if template_id == template_service.BUILTIN_HANDDRAWN_TEMPLATE_ID:
        _, paths = template_service.builtin_sources(context)
        if index < 1 or index > len(paths):
            raise HTTPException(status_code=404, detail="模板参考图不存在")
        return FileResponse(str(paths[index - 1]), media_type="image/png")
    source = template_service.template_dir_or_404(context, template_id)
    detail = template_service.template_detail(context, template_id)
    image = next(
        (
            item
            for item in detail["references"]["images"]
            if int(item.get("index", 0)) == index
        ),
        None,
    )
    if image is None:
        raise HTTPException(status_code=404, detail="模板参考图不存在")
    path = (source / "references" / Path(str(image["filename"])).name).resolve()
    if path.parent != (source / "references").resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="模板参考图不存在")
    return FileResponse(str(path), media_type="image/png")


@router.post("/api/projects/{project_id}/steps/3/image-style/templates")
def save_step3_template(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    result = template_service.save_named_template(
        _context(),
        project,
        str((payload or {}).get("name") or ""),
    )
    return {"success": True, **result}


@router.post("/api/projects/{project_id}/steps/3/image-style/templates/{template_id}/apply")
def apply_step3_template(
    project_id: str,
    template_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    outcome = template_service.apply_named_template(
        _context(),
        project,
        template_id,
    )
    return {
        "success": True,
        "style": outcome["style"],
        "references": _step3_references(project, project_id),
    }


@router.delete("/api/image-style/project-templates/{template_id}")
def delete_step3_template(template_id: str) -> dict[str, Any]:
    items = template_service.delete_named_template(_context(), template_id)
    return {"success": True, "templates": items}
