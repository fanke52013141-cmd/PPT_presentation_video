"""Agent style adapters: project profile, Step 3 style, references, templates,
global image style and IP characters."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from agent_contract.domains.freeform import FreeFormRequest
from database import get_db

import project_style_routes
import global_image_style_routes
import ip_character_routes

router = APIRouter()


@router.get("/style/profile-templates")
def agent_get_profile_templates() -> dict[str, Any]:
    return project_style_routes.get_project_profile_templates()


@router.get("/projects/{project_id}/style/profile")
def agent_get_project_profile(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return project_style_routes.get_project_profile(project_id, db)


@router.put("/projects/{project_id}/style/profile")
def agent_save_project_profile(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return project_style_routes.save_project_profile(project_id, payload.payload, db)


@router.post("/style/generate")
def agent_generate_project_style(payload: FreeFormRequest) -> dict[str, Any]:
    return project_style_routes.generate_project_image_style(payload.payload)


@router.get("/style/reverse-settings")
def agent_get_reverse_settings() -> dict[str, Any]:
    return project_style_routes.get_reverse_style_prompt_settings()


@router.put("/style/reverse-settings")
def agent_update_reverse_settings(payload: FreeFormRequest) -> dict[str, Any]:
    return project_style_routes.update_reverse_style_prompt_settings(payload.payload)


@router.post("/projects/{project_id}/style/reverse")
async def agent_reverse_style(
    project_id: str,
    files: list[UploadFile] = File(...),
    requirement: str = Form(""),
    apply: bool = Form(True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return await project_style_routes.reverse_step3_image_style(
        project_id, files=files, requirement=requirement, apply=apply, db=db
    )


@router.post("/projects/{project_id}/style/reverse-legacy")
async def agent_reverse_style_legacy(
    project_id: str,
    files: list[UploadFile] = File(...),
    requirement: str = Form(""),
    apply: bool = Form(True),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return await project_style_routes.reverse_legacy_project_image_style(
        project_id, files=files, requirement=requirement, apply=apply, db=db
    )


@router.get("/projects/{project_id}/style")
def agent_get_style(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return project_style_routes.get_step3_image_style(project_id, db)


@router.put("/projects/{project_id}/style")
def agent_update_style(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return project_style_routes.put_step3_image_style(project_id, payload.payload, db)


@router.get("/style/reference-settings")
def agent_get_reference_settings() -> dict[str, Any]:
    return project_style_routes.get_reference_generation_prompt_settings()


@router.put("/style/reference-settings")
def agent_update_reference_settings(payload: FreeFormRequest) -> dict[str, Any]:
    return project_style_routes.update_reference_generation_prompt_settings(payload.payload)


@router.get("/projects/{project_id}/style/references")
def agent_list_references(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return project_style_routes.list_step3_reference_images(project_id, db)


@router.post("/projects/{project_id}/style/references/generate")
def agent_generate_references(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return project_style_routes.generate_step3_reference_images(
        project_id, payload=payload.payload or None, db=db
    )


@router.post("/projects/{project_id}/style/references/upload")
async def agent_upload_references(
    project_id: str,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return await project_style_routes.upload_step3_reference_images(project_id, files=files, db=db)


@router.get("/projects/{project_id}/style/references/{index}/content")
def agent_get_reference(
    project_id: str, index: int, db: Session = Depends(get_db)
) -> FileResponse:
    return project_style_routes.get_step3_reference_image(project_id, index, db)


@router.delete("/projects/{project_id}/style/references/{index}")
def agent_delete_reference(project_id: str, index: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    return project_style_routes.delete_step3_reference_image(project_id, index, db)


@router.delete("/projects/{project_id}/style/references")
def agent_delete_all_references(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return project_style_routes.delete_all_step3_reference_images(project_id, db)


@router.get("/projects/{project_id}/style/references-legacy")
def agent_list_references_legacy(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return project_style_routes.list_legacy_reference_images(project_id, db)


@router.post("/projects/{project_id}/style/references-legacy/generate")
def agent_generate_references_legacy(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return project_style_routes.generate_legacy_reference_images(
        project_id, payload=payload.payload or None, db=db
    )


@router.get("/projects/{project_id}/style/references-legacy/{index}/content")
def agent_get_reference_legacy(
    project_id: str, index: int, db: Session = Depends(get_db)
) -> FileResponse:
    return project_style_routes.get_legacy_reference_image(project_id, index, db)


@router.delete("/projects/{project_id}/style/references-legacy/{index}")
def agent_delete_reference_legacy(
    project_id: str, index: int, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return project_style_routes.delete_legacy_reference_image(project_id, index, db)


@router.delete("/projects/{project_id}/style/references-legacy")
def agent_delete_all_references_legacy(
    project_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return project_style_routes.delete_all_legacy_reference_images(project_id, db)


@router.get("/style/templates")
def agent_list_style_templates() -> dict[str, Any]:
    return project_style_routes.list_step3_templates()


@router.get("/style/templates/{template_id}")
def agent_get_style_template(template_id: str) -> dict[str, Any]:
    return project_style_routes.get_step3_template_detail(template_id)


@router.post("/style/templates")
def agent_create_style_template(payload: FreeFormRequest) -> dict[str, Any]:
    return project_style_routes.create_account_style_template(payload.payload)


@router.post("/style/templates/with-references")
async def agent_create_style_template_with_references(
    name: str = Form(...),
    system_content: str = Form(...),
    style_summary: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> dict[str, Any]:
    return await project_style_routes.create_account_style_template_with_references(
        name=name, system_content=system_content, style_summary=style_summary, files=files
    )


@router.get("/style/templates/{template_id}/references/{index}/content")
def agent_get_template_reference(template_id: str, index: int) -> FileResponse:
    return project_style_routes.get_step3_template_reference(template_id, index)


@router.post("/projects/{project_id}/style/templates")
def agent_save_project_style_template(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return project_style_routes.save_step3_template(project_id, payload.payload, db)


@router.post("/projects/{project_id}/style/templates/{template_id}/apply")
def agent_apply_project_style_template(
    project_id: str, template_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return project_style_routes.apply_step3_template(project_id, template_id, db)


@router.delete("/style/templates/{template_id}")
def agent_delete_style_template(template_id: str) -> dict[str, Any]:
    return project_style_routes.delete_step3_template(template_id)


# ---- 全局图片风格 ----

@router.get("/global-image-style")
def agent_get_global_style() -> dict[str, Any]:
    return global_image_style_routes.get_image_style()


@router.put("/global-image-style")
def agent_update_global_style(payload: FreeFormRequest) -> dict[str, Any]:
    return global_image_style_routes.update_image_style(payload.payload)


@router.post("/global-image-style/validate")
def agent_validate_global_style(payload: FreeFormRequest) -> dict[str, Any]:
    return global_image_style_routes.validate_image_style(payload.payload)


@router.get("/global-image-style/templates")
def agent_list_global_templates() -> dict[str, Any]:
    return global_image_style_routes.get_image_style_templates()


@router.get("/global-image-style/templates/{template_id}")
def agent_get_global_template(template_id: str) -> dict[str, Any]:
    return global_image_style_routes.get_image_style_template(template_id)


@router.post("/global-image-style/templates")
def agent_save_global_template(payload: FreeFormRequest) -> dict[str, Any]:
    return global_image_style_routes.save_image_style_template(payload.payload)


@router.delete("/global-image-style/templates/{template_id}")
def agent_delete_global_template(template_id: str) -> dict[str, Any]:
    return global_image_style_routes.delete_image_style_template(template_id)


@router.get("/global-image-style/reference/{kind}/content")
def agent_get_global_reference(kind: str) -> FileResponse:
    return global_image_style_routes.get_image_style_reference(kind)


@router.put("/global-image-style/reference/{kind}")
def agent_update_global_reference(kind: str, file: UploadFile = File(...)) -> dict[str, Any]:
    return global_image_style_routes.update_image_style_reference(kind, file)


@router.post("/global-image-style/template-references/apply")
def agent_apply_global_template_references(payload: FreeFormRequest) -> dict[str, Any]:
    return global_image_style_routes.apply_image_style_template_references(payload.payload)


# ---- IP 角色 ----

@router.get("/projects/{project_id}/ip-characters")
def agent_list_ip_characters(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return ip_character_routes.get_ip_characters(project_id, db)


@router.post("/projects/{project_id}/ip-characters")
def agent_upsert_ip_character(
    project_id: str,
    data: str = Form("{}", description="JSON string of character payload"),
    file: UploadFile = File(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ip_character_routes.upsert_ip_character(project_id, data, file, db)


@router.put("/projects/{project_id}/ip-characters/config")
def agent_update_ip_config(
    project_id: str,
    payload: FreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return ip_character_routes.update_ip_character_config(project_id, payload.payload, db)


@router.delete("/projects/{project_id}/ip-characters/{character_id}")
def agent_delete_ip_character(
    project_id: str, character_id: str, db: Session = Depends(get_db)
) -> dict[str, Any]:
    return ip_character_routes.delete_ip_character(project_id, character_id, db)


@router.get("/projects/{project_id}/ip-characters/{character_id}/image")
def agent_get_ip_image(
    project_id: str, character_id: str, db: Session = Depends(get_db)
) -> FileResponse:
    return ip_character_routes.get_ip_character_image(project_id, character_id, db)
