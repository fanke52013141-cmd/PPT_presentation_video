"""Explicit HTTP routes for reusable creation configuration packages."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from account_context import get_current_account_id
from account_service import set_default_creation_config
from database import Account, get_db

from creation_config_models import (
    CreationConfigArchive,
    CreationConfigCopy,
    CreationConfigCreate,
    CreationConfigImport,
    CreationConfigResolve,
    CreationConfigUpdate,
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


@router.get("/api/creation-configs/default-payload")
def get_default_creation_config_payload() -> dict[str, Any]:
    from creation_config_defaults import default_creation_config_payload

    return {
        "success": True,
        "payload": default_creation_config_payload(),
    }


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


@router.put("/api/creation-configs/{package_id}")
def update_creation_config(
    package_id: str,
    payload: CreationConfigUpdate,
) -> dict[str, Any]:
    return _run(
        lambda: {
            "success": True,
            "package": service.update_creation_config(
                package_id,
                **payload.model_dump(),
            ),
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


@router.delete("/api/creation-configs/{package_id}")
def delete_creation_config(
    package_id: str,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Remove a package from future selection while retaining project history."""

    def operation() -> dict[str, Any]:
        # Resolve ownership before checking the database so a guessed package
        # ID never reveals another account's default configuration.
        package = service.get_creation_config(package_id)
        account = db.query(Account).filter(Account.id == get_current_account_id()).first()
        deleted = service.delete_creation_config(package_id)
        default_cleared = False
        if (
            account is not None
            and account.default_creation_config_package_id == package["id"]
        ):
            # A deleted default must not leave the account pointing at an
            # archived package.  The reusable package stays archived so
            # historical project snapshots remain reproducible.
            set_default_creation_config(db, account.id, None, None)
            default_cleared = True
        return {
            "success": True,
            "package": deleted,
            "default_cleared": default_cleared,
            "message": (
                "创作包已删除，已清除当前账号默认创作包；已有项目的配置快照保持不变。"
                if default_cleared
                else "创作包已删除，不再用于新项目；已有项目的配置快照保持不变。"
            ),
        }

    return _run(operation)


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

