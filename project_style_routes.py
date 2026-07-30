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

from database import Project, get_db
import image_style_reverse_service as reverse_service
import project_profile_service
import project_profile_store
from project_style_context import get_project_style_context
import project_style_reference_service as reference_service
import project_style_reference_store as reference_store
import project_style_template_service as template_service
import step3_image_style_service as style_service


router = APIRouter()

AUTOMATION_MODES = [
    {"id": "manual_review", "name": "手动审核模式", "description": "按原流程逐步生成、检查和确认。"},
    {"id": "auto", "name": "全自动模式", "description": "配合一键生成运行完整链路；失败时暂停给用户处理。"},
]


def _context() -> Any:
    return get_project_style_context()


def _project_or_404(db: Session, project_id: str) -> Project:
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


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
    profile = project_profile_store._normalize_lightweight_profile(
        project_profile_store._read_json(
            project_profile_store._profile_path(project),
            {},
        ),
        {},
    )
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
    existing = project_profile_store._read_json(
        project_profile_store._profile_path(project),
        {},
    )
    profile = project_profile_store._normalize_lightweight_profile(
        payload if isinstance(payload, dict) else {},
        existing,
    )
    project_profile_store._write_json(
        project_profile_store._profile_path(project),
        profile,
    )
    _log(project, "project_profile_saved_lightweight", profile=profile)
    return {"success": True, "profile": profile}


@router.post("/api/project-profile/image-style/generate")
def generate_project_image_style(payload: dict[str, Any]) -> dict[str, Any]:
    style = project_profile_service._generate_image_style_with_llm(
        _context(),
        payload if isinstance(payload, dict) else {},
    )
    return {"success": True, "style": style}


@router.get("/api/settings/image-style-reverse")
def get_reverse_style_prompt_settings() -> dict[str, Any]:
    system_content, output_example = reverse_service._read_reverse_style_prompts(
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
    system_content = reverse_service._safe_text(prompts.get("system_content"), 30000)
    output_example = reverse_service._safe_text(prompts.get("output_example"), 20000)
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
    saved = reverse_service._save_uploaded_references(context, project, files)
    requirement_text = reverse_service._safe_text(requirement, 4000)
    raw_style = reverse_service._call_vision_model(
        context,
        saved,
        project,
        requirement_text,
    )
    style = reverse_service._style_with_required_rules(
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
        style_service._save_step3_style(
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
        path=str(style_service._state_path(project)),
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
        reverse_service._apply_style_to_project(project, style) if apply else None
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
        "style_state": style_service._step3_style_state(project),
        "style": style_service._step3_style(project),
    }


@router.put("/api/projects/{project_id}/steps/3/image-style")
def put_step3_image_style(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    style = style_service._manual_style_from_payload(
        payload if isinstance(payload, dict) else {},
        style_service._step3_style(project),
    )
    if not style_service._safe_text(style.get("system_content"), 12000):
        raise HTTPException(
            status_code=400,
            detail="图片生成 System Content 不能为空",
        )
    state = style_service._save_step3_style(
        project,
        style,
        "manual_system_content",
    )
    _log(
        project,
        "step3_image_style_manual_saved",
        path=str(style_service._state_path(project)),
    )
    return {"success": True, "style": style, "style_state": state}


@router.get("/api/settings/image-style-reference-generation")
def get_reference_generation_prompt_settings() -> dict[str, Any]:
    system_content = reference_service._read_reference_generation_system_content(
        _context()
    )
    preview = reference_service._style_generation_prompt(
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
    system_content = reference_service._safe_text(
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
    return template_service._rewrite_reference_urls(
        reference_service._load_manifest(project, project_id),
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
    manifest = reference_service._generate_reference_images(
        _context(),
        project,
        project_id,
        payload if isinstance(payload, dict) else {},
    )
    return {
        "success": True,
        "references": template_service._rewrite_reference_urls(
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
    refs_dir = reference_service._references_dir(project)
    refs_dir.mkdir(parents=True, exist_ok=True)
    uploaded: list[dict[str, Any]] = []
    for index, file in enumerate(selected, start=1):
        content = await file.read()
        if not content:
            continue
        filename = f"style_reference_{index:02d}.png"
        _context().process_and_save_image(content, str(refs_dir / filename))
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
    reference_store._write_normalized_manifest(project, manifest)
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
    root = reference_service._references_dir(project).resolve()
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
        references = reference_store._delete_reference(project, project_id, index)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _log(project, "step3_image_style_reference_image_deleted", index=index)
    return {
        "success": True,
        "references": template_service._rewrite_reference_urls(
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
    references = reference_store._delete_all_references(project, project_id)
    _log(
        project,
        "step3_image_style_reference_images_deleted",
        count=references.get("deleted_count", 0),
    )
    return {
        "success": True,
        "references": template_service._rewrite_reference_urls(
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
        "references": reference_service._load_manifest(project, project_id),
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
    manifest = reference_service._generate_reference_images(
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


def _templates_root() -> Path:
    return Path(_context().DATA_DIR) / "step3_image_style_templates"


def _templates_index() -> Path:
    return _templates_root() / "index.json"


def _builtin_sources() -> tuple[Path, list[Path]]:
    context = _context()
    style_path = Path(context.HANDDRAWN_STYLE_TOKENS_PATH)
    reference_root = Path(context.REPO_ROOT) / "references" / "style_reference"
    paths = [
        reference_root / "PPT模板.png",
        reference_root / "PPT示例.png",
    ]
    return style_path, [path for path in paths if path.is_file()]


def _builtin_style() -> dict[str, Any]:
    style_path, _ = _builtin_sources()
    if not style_path.exists():
        raise HTTPException(status_code=404, detail="内置手绘风格配置缺失")
    try:
        style_tokens = yaml.safe_load(
            style_path.read_text(encoding="utf-8-sig")
        ) or {}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="内置手绘风格配置损坏",
        ) from exc
    if not isinstance(style_tokens, dict):
        raise HTTPException(status_code=500, detail="内置手绘风格配置损坏")
    system_content = _context().build_image_style_prompt(style_tokens)
    return {
        "source": "built_in_template",
        "template_id": template_service.BUILTIN_HANDDRAWN_TEMPLATE_ID,
        "style_name": template_service.BUILTIN_HANDDRAWN_TEMPLATE_NAME,
        "style_summary": "温暖极简的手绘线稿科普风格，纯白画布、清晰分组，适合演讲内容可视化与 Mask 显现。",
        "system_content": system_content,
        "sample_reference_image_prompts": [system_content],
        "reference_image_count_target": 3,
        "style_tokens": style_tokens,
    }


def _read_templates() -> list[dict[str, Any]]:
    value = template_service._read_json(_templates_index(), {"templates": []})
    items = value.get("templates", []) if isinstance(value, dict) else []
    return [item for item in items if isinstance(item, dict)]


def _write_templates(items: list[dict[str, Any]]) -> None:
    template_service._write_json(
        _templates_index(),
        {"version": "step3_image_style_templates_v1", "templates": items},
    )


def _template_dir_or_404(template_id: str) -> Path:
    if len(template_id) != 12 or any(char not in "0123456789abcdef" for char in template_id):
        raise HTTPException(status_code=404, detail="图片风格模板不存在")
    root = _templates_root().resolve()
    path = (root / template_id).resolve()
    if path.parent != root or not path.exists():
        raise HTTPException(status_code=404, detail="图片风格模板不存在")
    return path


def _template_detail(template_id: str) -> dict[str, Any]:
    if template_id == template_service.BUILTIN_HANDDRAWN_TEMPLATE_ID:
        _, paths = _builtin_sources()
        images = [
            {
                "index": index,
                "filename": path.name,
                "source": "built_in_template",
                "url": f"/api/image-style/project-templates/{template_id}/reference-images/{index}?t={int(path.stat().st_mtime)}",
            }
            for index, path in enumerate(paths[:3], start=1)
        ]
        item = {
            "id": template_id,
            "name": template_service.BUILTIN_HANDDRAWN_TEMPLATE_NAME,
            "built_in": True,
            "reference_count": len(images),
        }
        return {
            "success": True,
            "template": item,
            "style": _builtin_style(),
            "references": {
                "scope": "step3_image_style_template",
                "style_name": item["name"],
                "images": images,
            },
        }
    source = _template_dir_or_404(template_id)
    style = template_service._read_json(source / "style.json", {})
    manifest = template_service._read_json(source / "references.json", {})
    normalized = []
    for item in (manifest.get("images", []) if isinstance(manifest, dict) else [])[:3]:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except Exception:
            continue
        filename = Path(str(item.get("filename") or f"style_reference_{index:02d}.png")).name
        path = (source / "references" / filename).resolve()
        if path.parent != (source / "references").resolve() or not path.is_file():
            continue
        normalized.append({
            **item,
            "index": index,
            "filename": filename,
            "url": f"/api/image-style/project-templates/{template_id}/reference-images/{index}?t={int(path.stat().st_mtime)}",
        })
    summary = next(
        (
            item
            for item in _read_templates()
            if str(item.get("id") or "") == template_id
        ),
        {},
    )
    return {
        "success": True,
        "template": summary,
        "style": style if isinstance(style, dict) else {},
        "references": {
            "scope": "step3_image_style_template",
            "style_name": str(
                (style or {}).get("style_name") or summary.get("name") or ""
            ),
            "images": normalized,
        },
    }


@router.get("/api/image-style/project-templates")
def list_step3_templates() -> dict[str, Any]:
    _, paths = _builtin_sources()
    built_in = {
        "id": template_service.BUILTIN_HANDDRAWN_TEMPLATE_ID,
        "name": template_service.BUILTIN_HANDDRAWN_TEMPLATE_NAME,
        "built_in": True,
        "reference_count": min(3, len(paths)),
    }
    return {"success": True, "templates": [built_in, *_read_templates()]}


@router.get("/api/image-style/project-templates/{template_id}")
def get_step3_template_detail(template_id: str) -> dict[str, Any]:
    return _template_detail(template_id)


@router.get("/api/image-style/project-templates/{template_id}/reference-images/{index}")
def get_step3_template_reference(
    template_id: str,
    index: int,
) -> FileResponse:
    if template_id == template_service.BUILTIN_HANDDRAWN_TEMPLATE_ID:
        _, paths = _builtin_sources()
        if index < 1 or index > len(paths):
            raise HTTPException(status_code=404, detail="模板参考图不存在")
        return FileResponse(str(paths[index - 1]), media_type="image/png")
    source = _template_dir_or_404(template_id)
    detail = _template_detail(template_id)
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
    name = str((payload or {}).get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="模板名称不能为空")
    if len(name) > 120:
        raise HTTPException(status_code=400, detail="模板名称不能超过 120 个字符")
    state = template_service._read_json(
        template_service._step3_state_path(project),
        {},
    )
    style = state.get("image_style_profile") if isinstance(state.get("image_style_profile"), dict) else {}
    if not str(style.get("system_content") or "").strip():
        raise HTTPException(status_code=400, detail="请先保存图片生成 System Content")
    manifest = template_service._read_json(
        reference_store._manifest_path(project),
        {},
    )
    if not (manifest.get("images", []) if isinstance(manifest, dict) else []):
        raise HTTPException(status_code=400, detail="请先生成或上传至少 1 张效果预览")
    items = _read_templates()
    if any(str(item.get("name") or "").strip().casefold() == name.casefold() for item in items):
        raise HTTPException(status_code=400, detail="模板名称已存在，请换一个名称")
    template_id = uuid.uuid4().hex[:12]
    target = _templates_root() / template_id
    target.mkdir(parents=True, exist_ok=False)
    template_service._write_json(target / "style.json", style)
    template_service._write_json(target / "references.json", manifest)
    source_refs = reference_store._references_dir(project)
    if source_refs.exists():
        shutil.copytree(source_refs, target / "references", dirs_exist_ok=True)
    item = {
        "id": template_id,
        "name": name,
        "reference_count": len(manifest.get("images", [])),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    items.append(item)
    _write_templates(items)
    return {"success": True, "template": item, "templates": items}


@router.post("/api/projects/{project_id}/steps/3/image-style/templates/{template_id}/apply")
def apply_step3_template(
    project_id: str,
    template_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    project = _project_or_404(db, project_id)
    built_in = template_id == template_service.BUILTIN_HANDDRAWN_TEMPLATE_ID
    source = None if built_in else _template_dir_or_404(template_id)
    style = (
        _builtin_style()
        if built_in
        else template_service._read_json(source / "style.json", {})
    )
    if not style:
        raise HTTPException(status_code=400, detail="图片风格模板内容损坏")
    template_service._save_step3_style_state(
        project,
        style,
        "built_in_template" if built_in else "named_template",
    )
    target_refs = reference_store._references_dir(project)
    if target_refs.exists():
        shutil.rmtree(target_refs)
    if built_in:
        _, source_images = _builtin_sources()
        target_refs.mkdir(parents=True, exist_ok=True)
        images = []
        for index, source_image in enumerate(source_images[:3], start=1):
            filename = f"style_reference_{index:02d}.png"
            _context().process_and_save_image(
                source_image.read_bytes(),
                str(target_refs / filename),
            )
            images.append({
                "index": index,
                "filename": filename,
                "source": "built_in_template",
            })
        manifest = {
            "version": "step3_style_references_v1",
            "scope": "step3_image_style",
            "style_name": template_service.BUILTIN_HANDDRAWN_TEMPLATE_NAME,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "images": images,
        }
    else:
        source_refs = source / "references"
        if source_refs.exists():
            shutil.copytree(source_refs, target_refs)
        manifest = template_service._read_json(source / "references.json", {})
    reference_store._write_normalized_manifest(
        project,
        manifest if isinstance(manifest, dict) else {},
    )
    return {
        "success": True,
        "style": style,
        "references": _step3_references(project, project_id),
    }


@router.delete("/api/image-style/project-templates/{template_id}")
def delete_step3_template(template_id: str) -> dict[str, Any]:
    if template_id == template_service.BUILTIN_HANDDRAWN_TEMPLATE_ID:
        raise HTTPException(status_code=400, detail="内置手绘风格不能删除")
    source = _template_dir_or_404(template_id)
    items = [
        item
        for item in _read_templates()
        if str(item.get("id") or "") != template_id
    ]
    shutil.rmtree(source)
    _write_templates(items)
    return {"success": True, "templates": items}
