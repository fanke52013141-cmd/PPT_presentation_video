"""HTTP surface for the reusable model connection registry.

The application composition root must configure the service dependencies and
include ``router``.  This module does not own database or credential storage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

import model_connection_service as service
from scripts.media_tools import probe_media_duration_sec
from model_connection_models import (
    ModelConnectionCopy,
    ModelConnectionCreate,
    ModelConnectionStateUpdate,
    ModelConnectionUpdate,
)


router = APIRouter(prefix="/api/model-connections", tags=["Model connections"])
_VOICE_REFERENCE_ROOT = Path(__file__).resolve().parent / "data" / "model_voice_references"


def _raise_http_error(exc: Exception) -> None:
    if isinstance(exc, service.ModelConnectionNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, service.ModelConnectionUnavailableError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    raise exc


@router.get("")
def list_model_connections(
    kind: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False),
) -> dict[str, Any]:
    try:
        return {"connections": service.list_model_connections(kind=kind, include_archived=include_archived)}
    except Exception as exc:
        _raise_http_error(exc)


@router.post("")
def create_model_connection(payload: ModelConnectionCreate) -> dict[str, Any]:
    try:
        return service.create_model_connection(payload)
    except Exception as exc:
        _raise_http_error(exc)


@router.get("/{connection_id}")
def get_model_connection(connection_id: str) -> dict[str, Any]:
    try:
        return service.get_model_connection(connection_id)
    except Exception as exc:
        _raise_http_error(exc)


@router.put("/{connection_id}")
def update_model_connection(
    connection_id: str,
    payload: ModelConnectionUpdate,
) -> dict[str, Any]:
    try:
        return service.update_model_connection(connection_id, payload)
    except Exception as exc:
        _raise_http_error(exc)


@router.post("/{connection_id}/reference-audio")
async def upload_model_reference_audio(
    connection_id: str,
    file: UploadFile = File(...),
) -> dict[str, Any]:
    """Persist one reference file for a voice-cloning connection."""
    try:
        connection = service.get_model_connection(connection_id)
        revision = connection.get("revision") or {}
        if connection.get("kind") != "tts" or revision.get("provider") not in {
            "volcengine_seed_audio",
            "comfyui_tts",
        }:
            raise ValueError("仅豆包音频生成 1.0 或 ComfyUI / IndexTTS 模型可以上传参考音频")
        suffix = Path(str(file.filename or "")).suffix.lower()
        if suffix not in {".wav", ".mp3", ".pcm", ".ogg"}:
            raise ValueError("参考音频仅支持 wav、mp3、pcm 或 ogg 格式")
        content = await file.read()
        if not content or len(content) > 10 * 1024 * 1024:
            raise ValueError("参考音频必须存在且不能超过 10MB")
        _VOICE_REFERENCE_ROOT.mkdir(parents=True, exist_ok=True)
        target = _VOICE_REFERENCE_ROOT / f"{connection_id}{suffix}"
        pending = _VOICE_REFERENCE_ROOT / f"{connection_id}.upload{suffix}"
        pending.write_bytes(content)
        duration = probe_media_duration_sec(
            pending,
            repo_root=Path(__file__).resolve().parent,
        )
        if duration is None or duration <= 0:
            pending.unlink(missing_ok=True)
            raise ValueError("参考音频无法解码，请重新上传有效音频")
        if duration > 30:
            pending.unlink(missing_ok=True)
            raise ValueError("参考音频不能超过 30 秒")
        for existing in _VOICE_REFERENCE_ROOT.glob(f"{connection_id}.*"):
            if existing != pending:
                existing.unlink(missing_ok=True)
        pending.replace(target)
        public_config = dict(revision.get("public_config") or {})
        public_config["clone_voice_id"] = str(target)
        updated = service.update_model_connection(
            connection_id,
            ModelConnectionUpdate(public_config=public_config),
        )
        return {
            "connection": updated,
            "reference_audio": {
                "name": file.filename,
                "size": len(content),
                "duration_sec": round(duration, 3),
            },
        }
    except Exception as exc:
        _raise_http_error(exc)


@router.post("/{connection_id}/copy")
def copy_model_connection(
    connection_id: str,
    payload: ModelConnectionCopy,
) -> dict[str, Any]:
    try:
        return service.copy_model_connection(connection_id, payload)
    except Exception as exc:
        _raise_http_error(exc)


@router.put("/{connection_id}/state")
def update_model_connection_state(
    connection_id: str,
    payload: ModelConnectionStateUpdate,
) -> dict[str, Any]:
    try:
        return service.set_model_connection_state(connection_id, payload)
    except Exception as exc:
        _raise_http_error(exc)


@router.delete("/{connection_id}")
def delete_model_connection(connection_id: str) -> dict[str, Any]:
    try:
        return service.delete_model_connection(connection_id)
    except Exception as exc:
        _raise_http_error(exc)

