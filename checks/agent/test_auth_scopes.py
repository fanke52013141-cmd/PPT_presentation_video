"""Scope-model and deployment-guard regression tests (review 2026-10-24).

历史缺陷回顾：
1. ``_safe_scopes`` 对空/非法 scopes 静默发放全量权限（fail-open）。
2. ``config:*``/``account:manage`` 三种 scope 可授予但从未被强制；project:write
   令牌可铸造新令牌形成自我提权链。
3. Web 网络守卫放行的非回环部署中，Agent 面因使用独立凭据而仍处于匿名开放。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import database
from agent_api.auth import AGENT_API_KEY_ENV, AgentAuthMiddleware
from database import Account, Base


@pytest.fixture
def accounts_db(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'scopes.db'}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(Account(id="default", name="默认"))
        db.commit()
    monkeypatch.setattr(database, "SessionLocal", factory)
    yield factory
    engine.dispose()


# ------------------------------------------------------------------
# A1: _safe_scopes fail-closed
# ------------------------------------------------------------------

def test_omitted_scopes_default_to_read_only(accounts_db):
    from account_service import create_agent_token

    with accounts_db() as db:
        token = create_agent_token(db, "default")
        assert token["scopes"] == ["project:read"]


def test_all_invalid_scopes_rejected(accounts_db):
    from account_service import create_agent_token

    with accounts_db() as db:
        with pytest.raises(ValueError) as excinfo:
            create_agent_token(db, "default", scopes=["project:reed", "full:access"])
        assert "project:reed" in str(excinfo.value)


def test_declared_but_unenforced_scopes_rejected(accounts_db):
    """config:read/write 已从可授予集合移除——声明未强制的 scope 是模型缺陷。"""
    from account_service import create_agent_token

    with accounts_db() as db:
        with pytest.raises(ValueError):
            create_agent_token(db, "default", scopes=["config:read"])
        with pytest.raises(ValueError):
            create_agent_token(db, "default", scopes=["account:manage", "typo:scope"])


def test_valid_scopes_deduplicated_and_preserved(accounts_db):
    from account_service import create_agent_token

    with accounts_db() as db:
        token = create_agent_token(
            db, "default",
            scopes=["project:write", "project:read", "project:write", "account:manage"],
        )
        assert token["scopes"] == ["project:write", "project:read", "account:manage"]


# ------------------------------------------------------------------
# A2: account:manage enforcement on the direct-HTTP channel
# ------------------------------------------------------------------

def _scoped_app_with_accounts_route() -> FastAPI:
    """真实中间件 + 模拟 accounts 路由，验证中间件路径规则与 invoke 推导同源。"""
    app = FastAPI()
    app.add_middleware(AgentAuthMiddleware, prefix="/api/agent/v1")

    @app.post("/api/agent/v1/accounts")
    def _create_account():
        return {"ok": True}

    @app.get("/api/agent/v1/accounts/current")
    def _current_account():
        return {"ok": True}

    return app


def test_account_write_requires_account_manage_scope(accounts_db, monkeypatch):
    monkeypatch.setenv(AGENT_API_KEY_ENV, "legacy-key")
    client = TestClient(_scoped_app_with_accounts_route())

    def _token_header(scopes: str) -> dict:
        from account_service import create_agent_token

        with accounts_db() as db:
            raw = create_agent_token(db, "default", scopes=scopes.split(","))["token"]
        return {"Authorization": "Bearer " + raw}

    write_only = _token_header("project:read,project:write")
    response = client.post("/api/agent/v1/accounts", headers=write_only)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"

    manager = _token_header("project:read,project:write,account:manage")
    assert client.post("/api/agent/v1/accounts", headers=manager).status_code == 200
    # 读取自身账号保持只读可用（project:read 即可）
    readonly = _token_header("project:read")
    assert client.get("/api/agent/v1/accounts/current", headers=readonly).status_code == 200


def test_invoke_required_scope_matches_middleware_for_accounts():
    """invoke 通道与直连 HTTP 通道必须推导出同一 scope（防双通道分叉）。"""
    from agent_contract.capabilities import get_capability
    from agent_contract.discovery import required_scope

    for cap_id in ("accounts.create", "accounts.provision", "accounts.rename",
                   "accounts.delete", "accounts.default_config.update",
                   "accounts.agent_token.create"):
        assert required_scope(get_capability(cap_id)) == "account:manage", cap_id
    for cap_id in ("accounts.list", "accounts.current"):
        assert required_scope(get_capability(cap_id)) == "project:read", cap_id


# ------------------------------------------------------------------
# A4: non-loopback deployment guard for the Agent surface
# ------------------------------------------------------------------

from network_guard import validate_network_security  # noqa: E402


def test_loopback_never_needs_agent_key(monkeypatch):
    monkeypatch.delenv("PPT_AGENT_API_KEY", raising=False)
    validate_network_security("127.0.0.1")
    validate_network_security("localhost")
    validate_network_security("::1")


def test_non_loopback_requires_agent_key(monkeypatch):
    monkeypatch.delenv("PPT_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("PPT_STUDIO_ACCESS_TOKEN", "web-token")
    with pytest.raises(SystemExit) as excinfo:
        validate_network_security("192.168.1.10")
    assert "PPT_AGENT_API_KEY" in str(excinfo.value)


def test_non_loopback_agent_opt_in_allows(monkeypatch):
    monkeypatch.delenv("PPT_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("PPT_STUDIO_ACCESS_TOKEN", "web-token")
    monkeypatch.setenv("PPT_AGENT_ALLOW_INSECURE_AGENT_API", "1")
    validate_network_security("192.168.1.10")


def test_agent_key_alone_still_requires_web_guard(monkeypatch):
    """Agent 密钥不能替代 Web 面守卫——两面独立凭据、独立豁免。"""
    monkeypatch.setenv("PPT_AGENT_API_KEY", "agent-key")
    with pytest.raises(SystemExit):
        validate_network_security("192.168.1.10")


def test_both_tokens_satisfy_guard(monkeypatch):
    monkeypatch.setenv("PPT_STUDIO_ACCESS_TOKEN", "web-token")
    monkeypatch.setenv("PPT_AGENT_API_KEY", "agent-key")
    validate_network_security("192.168.1.10")
