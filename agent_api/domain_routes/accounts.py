"""Agent account adapters to the source-owned account service.

账号切换（select）是 Web 会话 Cookie 语义；Agent 连接通过令牌绑定账号，
故本模块不提供 select 适配。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agent_contract.domains.accounts import (
    AccountCreateRequest,
    AccountDefaultConfigRequest,
    AccountProvisionRequest,
    AccountRenameRequest,
    AgentTokenRequest,
)
from database import get_db

from account_context import get_current_account_id
from account_provisioning_service import provision_account_from_current
from account_service import (
    account_to_dict,
    create_account,
    create_agent_token,
    delete_account,
    get_account,
    list_accounts,
    rename_account,
    set_default_creation_config,
)

router = APIRouter()


@router.get("/accounts")
def agent_list_accounts(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"accounts": list_accounts(db)}


@router.get("/accounts/current")
def agent_current_account(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"account": account_to_dict(get_account(db, get_current_account_id()))}


@router.post("/accounts")
def agent_create_account(payload: AccountCreateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"account": create_account(
        db,
        name=payload.name,
        description=payload.description,
        default_package_id=None,
        default_package_version=None,
    )}


@router.post("/accounts/provision")
def agent_provision_account(
    payload: AccountProvisionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from account_provisioning_service import AccountProvisioningError

    try:
        return provision_account_from_current(
            db,
            **payload.model_dump(),
        )
    except AccountProvisioningError as exc:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/accounts/{account_id}")
def agent_rename_account(
    account_id: str,
    payload: AccountRenameRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return {"account": rename_account(db, account_id, name=payload.name)}


@router.delete("/accounts/{account_id}")
def agent_delete_account(account_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    return delete_account(db, account_id)


@router.put("/accounts/{account_id}/default-config")
def agent_set_default_config(
    account_id: str,
    payload: AccountDefaultConfigRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from fastapi import HTTPException

    if payload.package_id:
        import creation_config_service
        from account_service import account_scope

        try:
            with account_scope(account_id):
                creation_config_service.resolve_creation_config(
                    payload.package_id, version=payload.version, overrides={}
                )
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"默认创作配置不可用: {exc}") from exc
    return {"account": set_default_creation_config(db, account_id, payload.package_id, payload.version)}


@router.post("/accounts/{account_id}/agent-tokens")
def agent_create_agent_token(
    account_id: str,
    payload: AgentTokenRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    from agent_api.errors import ValidationFailedError

    try:
        return {"token": create_agent_token(db, account_id, name=payload.name, scopes=payload.scopes)}
    except ValueError as exc:
        raise ValidationFailedError(str(exc)) from exc
