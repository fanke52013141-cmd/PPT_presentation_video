"""Tests for the Agent API rate-limiting middleware."""

from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agent_api.rate_limit import AgentRateLimitMiddleware


def _make_app(max_requests: int = 3, window: int = 60) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        AgentRateLimitMiddleware,
        prefix="/api/agent/v1",
        max_requests=max_requests,
        window_seconds=window,
    )

    @app.get("/api/agent/v1/ping")
    def _ping():
        return {"ok": True}

    @app.get("/api/other")
    def _other():
        return {"ok": True}

    return app


def test_allows_requests_within_limit():
    app = _make_app(max_requests=5)
    client = TestClient(app)
    for _ in range(5):
        resp = client.get("/api/agent/v1/ping")
        assert resp.status_code == 200


def test_blocks_when_exceeded():
    app = _make_app(max_requests=2)
    client = TestClient(app)
    client.get("/api/agent/v1/ping")
    client.get("/api/agent/v1/ping")
    resp = client.get("/api/agent/v1/ping")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    assert resp.headers["X-RateLimit-Remaining"] == "0"
    body = resp.json()
    assert body["error"]["code"] == "RATE_LIMITED"


def test_does_not_limit_other_paths():
    app = _make_app(max_requests=1)
    client = TestClient(app)
    resp = client.get("/api/agent/v1/ping")
    assert resp.status_code == 200
    # Non-agent paths should not be rate-limited.
    for _ in range(10):
        resp = client.get("/api/other")
        assert resp.status_code == 200


def test_different_clients_have_separate_limits():
    app = _make_app(max_requests=2)
    client_a = TestClient(app)
    client_b = TestClient(app)
    # Client A uses up its quota.
    client_a.get("/api/agent/v1/ping", headers={"X-Agent-Token": "token-a"})
    client_a.get("/api/agent/v1/ping", headers={"X-Agent-Token": "token-a"})
    resp_a = client_a.get("/api/agent/v1/ping", headers={"X-Agent-Token": "token-a"})
    assert resp_a.status_code == 429
    # Client B should still have quota.
    resp_b = client_b.get("/api/agent/v1/ping", headers={"X-Agent-Token": "token-b"})
    assert resp_b.status_code == 200


def test_rate_limit_headers_on_success():
    app = _make_app(max_requests=10)
    client = TestClient(app)
    resp = client.get("/api/agent/v1/ping")
    assert resp.status_code == 200
    assert resp.headers["X-RateLimit-Limit"] == "10"
    assert int(resp.headers["X-RateLimit-Remaining"]) == 9


def test_forwarded_for_is_ignored_without_explicit_proxy_trust():
    """A direct caller cannot evade a quota by rotating X-Forwarded-For."""
    app = _make_app(max_requests=1)
    client = TestClient(app)
    assert client.get("/api/agent/v1/ping", headers={"X-Forwarded-For": "198.51.100.1"}).status_code == 200
    assert client.get("/api/agent/v1/ping", headers={"X-Forwarded-For": "198.51.100.2"}).status_code == 429
