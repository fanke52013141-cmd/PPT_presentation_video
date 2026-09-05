"""Creative account and Agent-token management for the local studio."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from database import Account, AgentToken, utc_now_naive


def _safe_scopes(scopes: Iterable[str] | None) -> str:
    allowed = {
        "project:read", "project:write", "pipeline:write", "artifact:read",
        "config:read", "config:write", "account:manage",
    }
    values = [str(scope).strip() for scope in (scopes or []) if str(scope).strip() in allowed]
    return ",".join(dict.fromkeys(values)) or "project:read,project:write,pipeline:write,artifact:read"


def account_to_dict(account: Account) -> dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "description": account.description or "",
        "status": account.status,
        "default_creation_config": (
            {
                "package_id": account.default_creation_config_package_id,
                "version": account.default_creation_config_version,
            }
            if account.default_creation_config_package_id else None
        ),
        "created_at": account.created_at.isoformat() if account.created_at else None,
    }


def list_accounts(db: Session) -> list[dict[str, Any]]:
    return [account_to_dict(row) for row in db.query(Account).order_by(Account.created_at).all()]


def get_account(db: Session, account_id: str) -> Account:
    account = db.query(Account).filter(Account.id == account_id).first()
    if account is None or account.status != "active":
        raise HTTPException(status_code=404, detail="创作账号不存在或已停用")
    return account


def create_account(
    db: Session,
    *,
    name: str,
    description: str = "",
    default_package_id: str | None = None,
    default_package_version: int | None = None,
) -> dict[str, Any]:
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="账号名称不能为空")
    account = Account(
        id="acct_" + uuid.uuid4().hex[:16],
        name=normalized,
        description=description,
        default_creation_config_package_id=default_package_id,
        default_creation_config_version=default_package_version,
        created_at=utc_now_naive(),
        updated_at=utc_now_naive(),
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account_to_dict(account)


def set_default_creation_config(
    db: Session,
    account_id: str,
    package_id: str | None,
    version: int | None,
) -> dict[str, Any]:
    account = get_account(db, account_id)
    if package_id is None and version is not None:
        raise HTTPException(status_code=422, detail="指定配置版本时必须指定配置包")
    account.default_creation_config_package_id = package_id.strip() if package_id else None
    account.default_creation_config_version = version
    account.updated_at = utc_now_naive()
    db.commit()
    db.refresh(account)
    return account_to_dict(account)


def get_default_creation_config(account_id: str, db: Session) -> dict[str, Any] | None:
    account = get_account(db, account_id)
    if not account.default_creation_config_package_id:
        return None
    return {
        "package_id": account.default_creation_config_package_id,
        "version": account.default_creation_config_version,
    }


def create_agent_token(
    db: Session,
    account_id: str,
    *,
    name: str = "Agent",
    scopes: Iterable[str] | None = None,
) -> dict[str, Any]:
    get_account(db, account_id)
    raw = "ppt_" + secrets.token_urlsafe(32)
    token = AgentToken(
        id="agt_" + uuid.uuid4().hex[:16],
        account_id=account_id,
        name=name.strip() or "Agent",
        token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        scopes=_safe_scopes(scopes),
        created_at=utc_now_naive(),
    )
    db.add(token)
    db.commit()
    return {"id": token.id, "account_id": account_id, "name": token.name, "scopes": token.scopes.split(","), "token": raw}


def authenticate_agent_token(db: Session, raw_token: str) -> AgentToken | None:
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    token = db.query(AgentToken).filter(
        AgentToken.token_hash == token_hash,
        AgentToken.status == "active",
    ).first()
    if token is not None:
        account = db.query(Account).filter(
            Account.id == token.account_id,
            Account.status == "active",
        ).first()
        if account is None:
            return None
        token.last_used_at = utc_now_naive()
        db.commit()
    return token
