"""Explicit FastAPI routes for settings and configuration portability."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request, UploadFile

from app_security import verify_access_token
import config_portability_service as config_service
import settings_service as service
from settings_service import (
    SettingsUpdate,
    TestImagePayload,
    TestLlmPayload,
    TestTtsPayload,
)
from repository_paths import DATA_DIR


router = APIRouter()
_max_config_import_bytes: int | None = None

_COMFYUI_TTS_WORKFLOW_PATH = os.path.join(
    DATA_DIR, "digital_human", "comfyui_tts_workflow.json"
)
_MAX_TTS_WORKFLOW_BYTES = 1024 * 1024
_MAX_TTS_WORKFLOW_NODES = 500


def configure_settings_routes(
    *,
    max_config_import_bytes: int,
) -> None:
    global _max_config_import_bytes
    _max_config_import_bytes = max_config_import_bytes


def _config_import_limit() -> int:
    if _max_config_import_bytes is None:
        raise RuntimeError("Settings routes have not been configured")
    return _max_config_import_bytes


@router.get("/api/settings")
def get_settings() -> Dict[str, Any]:
    return service.get_settings()


@router.put("/api/settings")
def update_system_settings(
    payload: SettingsUpdate,
) -> Dict[str, Any]:
    return service.update_system_settings(payload)


@router.get("/api/config/export")
def export_full_config() -> Dict[str, Any]:
    return config_service.export_full_config()


@router.post("/api/config/export-with-secrets")
def export_full_config_with_secrets(
    payload: Dict[str, Any],
    request: Request,
) -> Dict[str, Any]:
    if not verify_access_token(request):
        raise HTTPException(
            status_code=401,
            detail="导出密钥需要有效的 PPT Studio access token。",
        )
    if str(payload.get("confirmation") or "") != "EXPORT_SECRETS":
        raise HTTPException(
            status_code=400,
            detail="Explicit secret-export confirmation is required.",
        )
    return config_service.export_full_config_with_secrets()


async def read_limited_json_request(
    request: Request,
    max_bytes: int,
) -> Dict[str, Any]:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"配置文件超过 "
                        f"{max_bytes // (1024 * 1024)} MB 限制"
                    ),
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Content-Length 格式不正确",
            )
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"配置文件超过 "
                    f"{max_bytes // (1024 * 1024)} MB 限制"
                ),
            )
    try:
        payload = json.loads(body.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400,
            detail="配置文件不是有效 JSON",
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="配置文件格式不正确",
        )
    return payload


@router.post("/api/config/import")
async def import_full_config(request: Request) -> Dict[str, Any]:
    payload = await read_limited_json_request(
        request,
        _config_import_limit(),
    )
    try:
        return config_service.import_full_config(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/settings/test-llm")
def test_llm_connection(
    payload: TestLlmPayload,
) -> Dict[str, Any]:
    return service.test_llm_connection(payload)


@router.post("/api/settings/test-image")
def test_image_connection(
    payload: TestImagePayload,
) -> Dict[str, Any]:
    return service.test_image_connection(payload)


@router.post("/api/settings/test-tts")
def test_tts_connection(
    payload: TestTtsPayload,
) -> Dict[str, Any]:
    return service.test_tts_connection(payload)


@router.get("/api/settings/comfyui-tts-workflow")
def get_comfyui_tts_workflow() -> Dict[str, Any]:
    path = Path(_COMFYUI_TTS_WORKFLOW_PATH)
    return {
        "exists": path.is_file(),
        "path": _COMFYUI_TTS_WORKFLOW_PATH,
    }


@router.post("/api/settings/comfyui-tts-workflow")
async def upload_comfyui_tts_workflow(file: UploadFile) -> Dict[str, Any]:
    # Read one byte past the declared limit so oversized uploads are rejected
    # before their complete payload is held in process memory.
    content = await file.read(_MAX_TTS_WORKFLOW_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="上传文件为空")
    if len(content) > _MAX_TTS_WORKFLOW_BYTES:
        raise HTTPException(status_code=413, detail="工作流文件过大（上限 1MB）")
    try:
        wf = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="工作流 JSON 解析失败") from exc
    if not isinstance(wf, dict) or not wf:
        raise HTTPException(status_code=400, detail="工作流 JSON 格式不正确")
    if len(wf) > _MAX_TTS_WORKFLOW_NODES:
        raise HTTPException(
            status_code=400,
            detail=f"工作流节点数过多：{len(wf)}（上限 {_MAX_TTS_WORKFLOW_NODES}）",
        )
    is_api_format = all(
        isinstance(v, dict) and "class_type" in v for v in wf.values()
    )
    if not is_api_format:
        raise HTTPException(
            status_code=400,
            detail="工作流不是 ComfyUI API 格式，请在 ComfyUI 中使用「Save (API Format)」导出后重新上传",
        )
    dest = Path(_COMFYUI_TTS_WORKFLOW_PATH)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(content)
    return {
        "success": True,
        "path": _COMFYUI_TTS_WORKFLOW_PATH,
        "nodes": len(wf),
    }
