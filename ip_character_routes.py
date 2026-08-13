"""Explicit FastAPI routes for IP character (IP 形象) management."""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from database import get_db
import ip_character_service as service


router = APIRouter()


@router.get("/api/projects/{project_id}/ip-characters")
def get_ip_characters(
    project_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.get_ip_characters(project_id, db)


@router.post("/api/projects/{project_id}/ip-characters")
def upsert_ip_character(
    project_id: str,
    data: str = Form("{}", description="JSON string of character payload"),
    file: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        payload = json.loads(data) if data else {}
    except json.JSONDecodeError:
        payload = {}
    return service.upsert_ip_character(project_id, payload, file, db)


@router.put("/api/projects/{project_id}/ip-characters/config")
def update_ip_character_config(
    project_id: str,
    payload: dict[str, Any],
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.update_ip_character_config(project_id, payload, db)


@router.delete("/api/projects/{project_id}/ip-characters/{character_id}")
def delete_ip_character(
    project_id: str,
    character_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return service.delete_ip_character(project_id, character_id, db)


@router.get("/api/projects/{project_id}/ip-characters/{character_id}/image")
def get_ip_character_image(
    project_id: str,
    character_id: str,
    db: Session = Depends(get_db),
) -> FileResponse:
    path = service.get_character_image_path(project_id, character_id, db)
    media = "image/png"
    lower = str(path).lower()
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        media = "image/jpeg"
    elif lower.endswith(".webp"):
        media = "image/webp"
    return FileResponse(str(path), media_type=media)
