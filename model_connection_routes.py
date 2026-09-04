"""HTTP surface for the reusable model connection registry.

The application composition root must configure the service dependencies and
include ``router``.  This module does not own database or credential storage.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

import model_connection_service as service
from model_connection_models import (
    ModelConnectionCopy,
    ModelConnectionCreate,
    ModelConnectionStateUpdate,
    ModelConnectionUpdate,
)


router = APIRouter(prefix="/api/model-connections", tags=["Model connections"])


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

