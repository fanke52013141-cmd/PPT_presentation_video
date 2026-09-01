"""Tests for the Agent API authentication middleware."""

from __future__ import annotations

import os
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_api.auth import AgentAuthMiddleware, AGENT_API_KEY_ENV


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AgentAuthMiddleware, prefix="/api/agent/v1")

    @app.get("/api/agent/v1/projects")
    def _list_projects():
        return {"projects": []}

    @app.get("/api/agent/v1/ping")
    def _ping():
        return {"ok": True}

    @app.get("/api/other")
    def _other():
        return {"ok": True}

    return app


@pytest.fixture
def with_api_key(monkeypatch):
    monkeypatch.setenv(AGENT_API_KEY_ENV, "secret-test-key-123")
    yield
    monkeypatch.delenv(AGENT_API_KEY_ENV, raising=False)


# ------------------------------------------------------------------
# No key configured → open access (development mode)
# ------------------------------------------------------------------

def test_no_key_allows_all():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/agent/v1/projects")
    assert resp.status_code == 200


# ------------------------------------------------------------------
# Key configured → authentication required
# ------------------------------------------------------------------

def test_missing_token_returns_401(with_api_key):
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/agent/v1/projects")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"] == "Bearer"
    assert resp.json()["error"]["code"] == "UNAUTHORIZED"


def test_bearer_token_success(with_api_key):
    app = _make_app()
    client = TestClient(app)
    resp = client.get(
        "/api/agent/v1/projects",
        headers={"Authorization": "Bearer secret-test-key-123"},
    )
    assert resp.status_code == 200


def test_api_key_header_success(with_api_key):
    app = _make_app()
    client = TestClient(app)
    resp = client.get(
        "/api/agent/v1/projects",
        headers={"X-API-Key": "secret-test-key-123"},
    )
    assert resp.status_code == 200


def test_agent_token_header_success(with_api_key):
    app = _make_app()
    client = TestClient(app)
    resp = client.get(
        "/api/agent/v1/projects",
        headers={"X-Agent-Token": "secret-test-key-123"},
    )
    assert resp.status_code == 200


def test_query_token_success_get_only(with_api_key):
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/agent/v1/projects?token=secret-test-key-123")
    assert resp.status_code == 200


def test_wrong_token_returns_401(with_api_key):
    app = _make_app()
    client = TestClient(app)
    resp = client.get(
        "/api/agent/v1/projects",
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401


def test_non_agent_paths_not_protected(with_api_key):
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/other")
    assert resp.status_code == 200


def test_public_ping_bypasses_auth(with_api_key):
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/agent/v1/ping")
    assert resp.status_code == 200
