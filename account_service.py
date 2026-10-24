"""Creative account and Agent-token management for the local studio."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
import uuid
from typing import Any, Iterable

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from database import Account, AgentToken, SessionLocal, utc_now_naive


# 当前鉴权层实际强制执行的 scope 全集（agent_api/auth.py 中间件与
# agent_contract/discovery.required_scope 同源推导）。声明未强制或强制未声明
# 都是权限模型缺陷：修改此集合必须同步两处消费方并补充测试。
ENFORCED_SCOPES = frozenset({
    "project:read", "project:write", "pipeline:write", "artifact:read",
    "account:manage",
})
DEFAULT_SCOPES = "project:read"


def _safe_scopes(scopes: Iterable[str] | None) -> str:
    """Normalize requested scopes; fail closed instead of widening access.

    省略 scopes 时只授予只读；提供了 scope 但存在非法值时直接拒绝创建，
    防止拼写错误静默退化为全量权限（历史缺陷：空/非法 scopes 曾默认发放全量）。
    """
    if scopes is None:
        return DEFAULT_SCOPES
    values = [str(scope).strip() for scope in scopes if str(scope).strip()]
    invalid = sorted({value for value in values if value not in ENFORCED_SCOPES})
    if invalid:
        raise ValueError(
            "未知的 scope: " + ", ".join(invalid)
            + f"（可用: {', '.join(sorted(ENFORCED_SCOPES))}）"
        )
    return ",".join(dict.fromkeys(values)) or DEFAULT_SCOPES


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


def list_accounts(db: Session, *, include_inactive: bool = False) -> list[dict[str, Any]]:
    query = db.query(Account)
    if not include_inactive:
        query = query.filter(Account.status == "active")
    return [account_to_dict(row) for row in query.order_by(Account.created_at, Account.id).all()]


def delete_account(db: Session, account_id: str) -> dict[str, Any]:
    """Remove an account from use while retaining its owned artifacts.

    Count and mutation share one SQL statement so concurrent deletions cannot
    remove the final active account. Existing Agent tokens stop authenticating
    because authentication also checks the owning account's status.
    """
    active_count = select(func.count()).select_from(Account).where(
        Account.status == "active"
    ).scalar_subquery()
    result = db.execute(update(Account).where(
        Account.id == account_id,
        Account.status == "active",
        active_count > 1,
    ).values(status="deleted", updated_at=utc_now_naive()),
        execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        get_account(db, account_id)
        raise HTTPException(status_code=409, detail="至少保留一个账号，不能删除最后一个账号")
    db.commit()
    return {"deleted": True, "account_id": account_id}


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


def rename_account(db: Session, account_id: str, *, name: str) -> dict[str, Any]:
    """Update only the human-readable account name.

    Account IDs are the ownership boundary for projects, connections, and
    configuration packages.  Keeping the ID stable makes a rename safe for
    every existing resource under the account.
    """
    normalized = name.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="账号名称不能为空")
    account = get_account(db, account_id)
    account.name = normalized
    account.updated_at = utc_now_naive()
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


# last_used_at 写节流：Agent 每个认证请求都写库会与业务写入竞争 SQLite
# 单写者（审查 2026-10-24 P2-7）。同一令牌至多每分钟落盘一次"最近使用"。
_LAST_USED_WRITE_INTERVAL_SECONDS = 60.0
_last_used_writes: dict[str, float] = {}
_last_used_lock = threading.Lock()


def reset_last_used_throttle() -> None:
    """测试辅助：清空 last_used_at 写节流状态。"""
    with _last_used_lock:
        _last_used_writes.clear()


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
        now = time.monotonic()
        with _last_used_lock:
            last_write = _last_used_writes.get(token.id, 0.0)
            should_write = now - last_write >= _LAST_USED_WRITE_INTERVAL_SECONDS
            if should_write:
                _last_used_writes[token.id] = now
        if should_write:
            token.last_used_at = utc_now_naive()
            db.commit()
    return token


def list_accounts_across_sessions() -> list[dict[str, Any]]:
    """Enumerate every account row for config portability (opens its own session)."""
    db = SessionLocal()
    try:
        return list_accounts(db, include_inactive=True)
    finally:
        db.close()


def upsert_account_with_explicit_id(
    *,
    account_id: str,
    name: str,
    description: str = "",
    status: str = "active",
    default_package_id: str | None = None,
    default_package_version: int | None = None,
) -> dict[str, Any]:
    """Create or update an account row keeping its exported ID (import path).

    Imported account IDs must stay stable so the model connections,
    configuration packages, credentials, and per-account style directories
    referenced by a portable bundle keep their ownership on this machine.
    Account metadata is restored verbatim from the bundle.
    """
    db = SessionLocal()
    try:
        account = db.query(Account).filter(Account.id == account_id).first()
        if account is None:
            account = Account(
                id=account_id,
                name=name or account_id,
                description=description,
                status=status or "active",
                default_creation_config_package_id=default_package_id,
                default_creation_config_version=default_package_version,
                created_at=utc_now_naive(),
                updated_at=utc_now_naive(),
            )
            db.add(account)
        else:
            account.name = name or account_id
            account.description = description
            account.status = status or account.status
            account.default_creation_config_package_id = (
                default_package_id or None
            )
            account.default_creation_config_version = default_package_version
            account.updated_at = utc_now_naive()
        db.commit()
        db.refresh(account)
        return account_to_dict(account)
    finally:
        db.close()
