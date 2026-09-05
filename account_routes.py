"""Local creative-account management routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from account_service import (
    account_to_dict, create_account, create_agent_token, get_account, list_accounts,
    set_default_creation_config,
)
from account_context import account_scope, get_current_account_id
from database import get_db
import creation_config_service

router = APIRouter(prefix="/api/accounts", tags=["Creative accounts"])


class AccountCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    default_package_id: str | None = None
    default_package_version: int | None = Field(None, ge=1)


class AccountDefaultConfigRequest(BaseModel):
    package_id: str | None = None
    version: int | None = Field(None, ge=1)


class AgentTokenRequest(BaseModel):
    name: str = Field("Agent", min_length=1, max_length=200)
    scopes: list[str] = Field(default_factory=list)


@router.get("")
def accounts(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"accounts": list_accounts(db)}


@router.get("/current")
def current_account(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"account": account_to_dict(get_account(db, get_current_account_id()))}


@router.post("")
def account_create(payload: AccountCreateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    if payload.default_package_id or payload.default_package_version is not None:
        raise HTTPException(
            status_code=422,
            detail="请先创建并切换到账号，再为该账号设置默认创作配置",
        )
    return {"account": create_account(db, name=payload.name, description=payload.description, default_package_id=payload.default_package_id, default_package_version=payload.default_package_version)}


@router.post("/{account_id}/select")
def account_select(account_id: str, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    account = get_account(db, account_id)
    response = {"account": {"id": account.id, "name": account.name}, "selected": True}
    from fastapi.responses import JSONResponse
    result = JSONResponse(response)
    result.set_cookie("ppt_studio_account_id", account.id, httponly=True, samesite="lax")
    return result


@router.put("/{account_id}/default-config")
def account_default_config(account_id: str, payload: AccountDefaultConfigRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    if payload.package_id:
        # A default must resolve inside the target account.  This prevents a
        # copied/stale ID from making future project creation fail at runtime.
        try:
            with account_scope(account_id):
                creation_config_service.resolve_creation_config(
                    payload.package_id,
                    version=payload.version,
                    overrides={},
                )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"默认创作配置不可用: {exc}") from exc
    return {"account": set_default_creation_config(db, account_id, payload.package_id, payload.version)}


@router.post("/{account_id}/agent-tokens")
def account_agent_token(account_id: str, payload: AgentTokenRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    # The token is returned only at creation time; callers must store it securely.
    return {"token": create_agent_token(db, account_id, name=payload.name, scopes=payload.scopes)}
