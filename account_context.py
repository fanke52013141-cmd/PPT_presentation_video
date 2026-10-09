"""Request-scoped creative-account identity.

Account identity is deliberately carried in a context variable instead of a
mutable module-level "current account".  That keeps browser requests,
background jobs, Agent clients, and MCP sessions from changing one another's
account while the local app is running.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Iterator

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


DEFAULT_ACCOUNT_ID = "default"

_account_id: ContextVar[str] = ContextVar(
    "ppt_studio_account_id", default=DEFAULT_ACCOUNT_ID
)


def get_current_account_id() -> str:
    return _account_id.get()


def set_current_account_id(account_id: str) -> Token[str]:
    normalized = str(account_id or "").strip()
    return _account_id.set(normalized or DEFAULT_ACCOUNT_ID)


def reset_current_account_id(token: Token[str]) -> None:
    _account_id.reset(token)


@contextmanager
def account_scope(account_id: str) -> Iterator[str]:
    token = set_current_account_id(account_id)
    try:
        yield get_current_account_id()
    finally:
        reset_current_account_id(token)


class AccountContextMiddleware(BaseHTTPMiddleware):
    """Select the browser account from a cookie/header for this request.

    Agent requests are selected by AgentAuthMiddleware and intentionally skip
    this middleware so a browser tab cannot override an Agent token identity.
    """

    async def dispatch(self, request, call_next):  # type: ignore[override]
        if request.url.path.startswith("/api/agent/v1"):
            return await call_next(request)
        account_id = (
            request.headers.get("x-ppt-account-id")
            or request.cookies.get("ppt_studio_account_id")
            or DEFAULT_ACCOUNT_ID
        ).strip()
        from database import SessionLocal
        db = SessionLocal()
        try:
            from database import Account
            account = db.query(Account).filter(
                Account.id == account_id, Account.status == "active"
            ).first()
            # Deleted browser selections (including the bootstrap default)
            # recover on another tab/restart; explicit header IDs stay strict.
            if account is None and not request.headers.get("x-ppt-account-id"):
                account = db.query(Account).filter(Account.status == "active").order_by(
                    Account.created_at, Account.id
                ).first()
                if account is not None:
                    account_id = account.id
        finally:
            db.close()
        if account is None:
            return JSONResponse({"detail": "创作账号不存在或已停用"}, status_code=404)
        token = set_current_account_id(account_id)
        try:
            response = await call_next(request)
            if not request.headers.get("x-ppt-account-id") and request.cookies.get("ppt_studio_account_id") != account_id:
                # Respect selection/deletion routes that already set this cookie.
                if not any("ppt_studio_account_id=" in value for value in response.headers.getlist("set-cookie")):
                    response.set_cookie("ppt_studio_account_id", account_id, httponly=True, samesite="lax")
            return response
        finally:
            reset_current_account_id(token)
