"""Explicit legacy-compatible routes for global image style."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

import global_image_style_service as service


router = APIRouter()


@router.get("/api/image-style")
def get_image_style() -> dict[str, Any]:
    return service.get_image_style()


@router.put("/api/image-style")
def update_image_style(payload: dict[str, Any]) -> dict[str, Any]:
    return service.update_image_style(payload)


@router.post("/api/image-style/validate")
def validate_image_style(payload: dict[str, Any]) -> dict[str, Any]:
    return service.validate_image_style(payload)


@router.get("/api/image-style/templates")
def get_image_style_templates() -> dict[str, Any]:
    return service.get_image_style_templates()


@router.get("/api/image-style/templates/{template_id}")
def get_image_style_template(template_id: str) -> dict[str, Any]:
    return service.get_image_style_template(template_id)


@router.post("/api/image-style/templates")
def save_image_style_template(
    payload: dict[str, Any],
) -> dict[str, Any]:
    return service.save_image_style_template(payload)


@router.delete("/api/image-style/templates/{template_id}")
def delete_image_style_template(
    template_id: str,
) -> dict[str, Any]:
    return service.delete_image_style_template(template_id)


@router.post(
    "/api/image-style/templates/{template_id}/apply-references"
)
def apply_image_style_template_references(
    template_id: str,
) -> dict[str, Any]:
    return service.apply_image_style_template_references(template_id)


@router.get(
    "/api/image-style/templates/{template_id}/reference/{kind}"
)
def get_image_style_template_reference(
    template_id: str,
    kind: str,
) -> FileResponse:
    return service.get_image_style_template_reference(
        template_id,
        kind,
    )


@router.get("/api/image-style/reference/{kind}")
def get_image_style_reference(kind: str) -> FileResponse:
    return service.get_image_style_reference(kind)


@router.post("/api/image-style/reference/{kind}")
def update_image_style_reference(
    kind: str,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    return service.update_image_style_reference(kind, file)
