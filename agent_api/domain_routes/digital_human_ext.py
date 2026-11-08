"""Agent digital-human adapters to the source-owned digital_human_routes.

config/health/generate-full already live in agent_api.domain_routes.digital_human;
this module covers the remaining business routes only. Every adapter forwards a
business ``HTTPException`` through the shared typed-error translator so Agents
receive machine-readable codes instead of the generic ``HTTP_ERROR`` fallback.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from agent_api.domain_routes.common import raise_typed_http_error
from agent_contract.domains.freeform import OptionalFreeFormRequest
from database import get_db

import digital_human_routes as dh

router = APIRouter()


@router.post("/projects/{project_id}/digital-human/motion")
async def agent_dh_upload_motion(
    project_id: str, file: UploadFile = File(...), db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await dh.upload_dh_motion(project_id, file=file, db=db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.post("/projects/{project_id}/digital-human/slides/{slide_id}/generate")
def agent_dh_generate_slide(
    project_id: str,
    slide_id: str,
    payload: OptionalFreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return dh.generate_dh(project_id, slide_id, payload=payload.payload, db=db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.get("/projects/{project_id}/digital-human/jobs/{job_id}")
def agent_dh_get_job(project_id: str, job_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return dh.get_dh_job(project_id, job_id, db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.get("/projects/{project_id}/digital-human/slides/{slide_id}/video")
def agent_dh_slide_video(
    project_id: str, slide_id: str, db: Session = Depends(get_db)
) -> FileResponse:
    try:
        return dh.get_dh_slide_video(project_id, slide_id, db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.post("/projects/{project_id}/digital-human/slides/{slide_id}/compose")
def agent_dh_compose_slide(
    project_id: str,
    slide_id: str,
    payload: OptionalFreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return dh.compose_dh_slide(project_id, slide_id, payload=payload.payload, db=db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.get("/projects/{project_id}/digital-human/slides/{slide_id}/composite-video")
def agent_dh_composite_video(
    project_id: str, slide_id: str, db: Session = Depends(get_db)
) -> FileResponse:
    try:
        return dh.get_dh_composite_video(project_id, slide_id, db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.post("/projects/{project_id}/digital-human/export-audio")
def agent_dh_export_audio(
    project_id: str,
    payload: OptionalFreeFormRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return dh.export_full_audio(project_id, payload=payload.payload, db=db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.get("/projects/{project_id}/digital-human/export-audio/content")
def agent_dh_full_audio(project_id: str, db: Session = Depends(get_db)) -> FileResponse:
    try:
        return dh.get_full_audio(project_id, db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.post("/projects/{project_id}/digital-human/upload")
async def agent_dh_upload_video(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await dh.upload_dh_video(project_id, file=file, db=db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.get("/projects/{project_id}/digital-human/upload/content")
def agent_dh_uploaded_video(project_id: str, db: Session = Depends(get_db)) -> FileResponse:
    try:
        return dh.get_dh_upload_video(project_id, db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.post("/projects/{project_id}/digital-human/avatars/upload")
async def agent_dh_upload_avatar(
    project_id: str,
    file: UploadFile = File(...),
    name: str = Form("数字人形象"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await dh.upload_dh_avatar(project_id, name=name, file=file, db=db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.get("/projects/{project_id}/digital-human/avatars")
def agent_dh_list_avatars(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return dh.list_dh_avatars(project_id, db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.post("/projects/{project_id}/digital-human/workflow/upload")
async def agent_dh_upload_workflow(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return await dh.upload_comfyui_workflow(project_id, file=file, db=db)
    except HTTPException as exc:
        raise_typed_http_error(exc)


@router.get("/projects/{project_id}/digital-human/workflow")
def agent_dh_get_workflow(project_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        return dh.get_comfyui_workflow(project_id, db)
    except HTTPException as exc:
        raise_typed_http_error(exc)
