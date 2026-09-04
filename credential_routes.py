"""HTTP metadata and write endpoints for credential references."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

import credential_store as service


class CredentialCreate(BaseModel):
    provider: str = Field(..., min_length=1, max_length=80)
    label: str = Field(..., min_length=1, max_length=120)
    secret_values: dict[str, str]


class CredentialUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=120)
    secret_values: dict[str, str] | None = None
    state: str | None = None


router = APIRouter(prefix="/api/credentials", tags=["Credentials"])


def _run(operation: Any) -> Any:
    try:
        return operation()
    except service.CredentialNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (service.CredentialUnavailable, service.CredentialError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("")
def list_credentials(
    include_disabled: bool = Query(default=False),
) -> dict[str, Any]:
    return _run(lambda: {"credentials": service.list_credentials(include_disabled=include_disabled)})


@router.post("")
def create_credential(payload: CredentialCreate) -> dict[str, Any]:
    return _run(lambda: {"credential": service.create_credential(**payload.model_dump())})


@router.put("/{credential_ref:path}")
def update_credential(credential_ref: str, payload: CredentialUpdate) -> dict[str, Any]:
    return _run(
        lambda: {
            "credential": service.update_credential(
                credential_ref,
                **payload.model_dump(exclude_unset=True),
            )
        }
    )
