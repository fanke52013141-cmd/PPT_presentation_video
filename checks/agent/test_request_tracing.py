"""Tests for Agent API request tracing middleware."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from agent_api.request_tracing import AgentRequestTracingMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(AgentRequestTracingMiddleware, prefix="/api/agent/v1")

    @app.get("/api/agent/v1/ping")
    def _ping(request: Request):
        rid = getattr(request.state, "request_id", None)
        return {"request_id": rid}

    return app


def test_generates_request_id_when_absent():
    app = _make_app()
    client = TestClient(app)
    resp = client.get("/api/agent/v1/ping")
    assert resp.status_code == 200
    rid = resp.headers.get("X-Request-ID")
    assert rid is not None
    assert len(rid) > 0
    # The handler should see the same ID on request.state.
    assert resp.json()["request_id"] == rid


def test_propagates_caller_provided_request_id():
    app = _make_app()
    client = TestClient(app)
    custom_id = "my-trace-123"
    resp = client.get("/api/agent/v1/ping", headers={"X-Request-ID": custom_id})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == custom_id
    assert resp.json()["request_id"] == custom_id


def test_truncates_overlong_request_id():
    app = _make_app()
    client = TestClient(app)
    long_id = "x" * 200
    resp = client.get("/api/agent/v1/ping", headers={"X-Request-ID": long_id})
    assert resp.status_code == 200
    rid = resp.headers["X-Request-ID"]
    assert len(rid) == 128


def test_no_tracing_header_for_non_agent_paths():
    app = FastAPI()
    app.add_middleware(AgentRequestTracingMiddleware, prefix="/api/agent/v1")

    @app.get("/api/other")
    def _other():
        return {"ok": True}

    client = TestClient(app)
    resp = client.get("/api/other")
    assert resp.status_code == 200
    assert "X-Request-ID" not in resp.headers
