"""Explicit HTTP routes for reusable creation configuration packages."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from creation_config_models import (
    CreationConfigArchive,
    CreationConfigCopy,
    CreationConfigCreate,
    CreationConfigImport,
    CreationConfigResolve,
    CreationConfigVersionCreate,
)
import creation_config_service as service


router = APIRouter()


def _run(operation: Any) -> Any:
    try:
        return operation()
    except service.CreationConfigNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except service.CreationConfigConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except service.CreationConfigValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except service.CreationConfigError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/creation-configs")
def list_creation_configs(
    include_archived: bool = Query(False),
) -> dict[str, Any]:
    return _run(
        lambda: {
            "success": True,
            "packages": service.list_creation_configs(
                include_archived=include_archived
            ),
        }
    )


@router.post("/api/creation-configs")
def create_creation_config(payload: CreationConfigCreate) -> dict[str, Any]:
    return _run(
        lambda: {
            "success": True,
            "package": service.create_creation_config(**payload.model_dump()),
        }
    )


@router.post("/api/creation-configs/import")
def import_creation_config(payload: CreationConfigImport) -> dict[str, Any]:
    return _run(
        lambda: {
            "success": True,
            "package": service.import_creation_config(**payload.model_dump()),
        }
    )


@router.get("/api/creation-configs/{package_id}")
def get_creation_config(package_id: str) -> dict[str, Any]:
    return _run(
        lambda: {
            "success": True,
            "package": service.get_creation_config(package_id),
        }
    )


@router.get("/api/creation-configs/{package_id}/versions/{version}")
def get_creation_config_version(
    package_id: str,
    version: int,
) -> dict[str, Any]:
    return _run(
        lambda: {
            "success": True,
            "version": service.get_creation_config_version(package_id, version),
        }
    )


@router.post("/api/creation-configs/{package_id}/copy")
def copy_creation_config(
    package_id: str,
    payload: CreationConfigCopy,
) -> dict[str, Any]:
    return _run(
        lambda: {
            "success": True,
            "package": service.copy_creation_config(
                package_id,
                **payload.model_dump(),
            ),
        }
    )


@router.post("/api/creation-configs/{package_id}/versions")
def create_creation_config_version(
    package_id: str,
    payload: CreationConfigVersionCreate,
) -> dict[str, Any]:
    return _run(
        lambda: {
            "success": True,
            "version": service.create_creation_config_version(
                package_id,
                **payload.model_dump(),
            ),
        }
    )


@router.put("/api/creation-configs/{package_id}/archive")
def archive_creation_config(
    package_id: str,
    payload: CreationConfigArchive,
) -> dict[str, Any]:
    return _run(
        lambda: {
            "success": True,
            "package": service.archive_creation_config(
                package_id,
                archived=payload.archived,
            ),
        }
    )


@router.post("/api/creation-configs/{package_id}/resolve")
def resolve_creation_config(
    package_id: str,
    payload: CreationConfigResolve,
) -> dict[str, Any]:
    return _run(
        lambda: {
            "success": True,
            "resolved": service.resolve_creation_config(
                package_id,
                **payload.model_dump(),
            ),
        }
    )

