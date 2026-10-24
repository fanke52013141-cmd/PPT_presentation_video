"""Typed error-code regression tests (review 2026-10-24 P1-4).

直接 HTTP 路由的业务错误历史上统一退化为 code=HTTP_ERROR，外部 Agent 只能
解析 message 文本。现在适配器在源头产出类型化 AgentAPIError；此文件锁定
"每类业务错误都有机器可读码 + 统一信封形状"。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def api():
    import server

    return TestClient(server.app, client=("agent-errors-" + uuid.uuid4().hex, 50000))


def _error_envelope(response) -> dict:
    body = response.json()
    assert "error" in body, response.text
    error = body["error"]
    # 信封形状完备：与 agent_error_handler 同一字段集（审查 P1-4 / errors.py）。
    for key in ("code", "message", "details", "retryable", "repair_actions"):
        assert key in error, f"missing {key}: {error}"
    return error


def test_model_connection_not_found_is_typed(api):
    detail = api.get("/api/agent/v1/capabilities/connections.get")
    assert detail.status_code == 200
    response = api.post("/api/agent/v1/invoke", json={
        "capability_id": "connections.get",
        "expected_contract_revision": detail.json()["contract_revision"],
        "arguments": {"connection_id": "mc_does_not_exist"},
    })
    assert response.status_code == 404, response.text
    error = _error_envelope(response)
    assert error["code"] == "NOT_FOUND", error


def test_model_connection_validation_error_is_typed(api):
    from model_connection_service import ModelConnectionCreate

    detail = api.get("/api/agent/v1/capabilities/connections.create")
    revision = detail.json()["contract_revision"]
    invalid = ModelConnectionCreate(
        kind="text", name="x", model="gpt-x", provider="openai",
        base_url="http://x", api_key="k",
    ).model_dump()
    invalid["kind"] = "no-such-kind"
    response = api.post("/api/agent/v1/invoke", json={
        "capability_id": "connections.create",
        "expected_contract_revision": revision,
        "arguments": invalid,
    })
    assert response.status_code in {400, 422}, response.text
    error = _error_envelope(response)
    assert error["code"] in {"VALIDATION_ERROR", "NOT_FOUND"}, error


def test_annotation_preview_404_is_typed(api):
    project = api.post("/api/agent/v1/invoke", json={
        "capability_id": "project.create",
        "expected_contract_revision": api.get("/api/agent/v1/capabilities/project.create").json()["contract_revision"],
        "arguments": {"name": "错误码测试项目"},
    }).json()["project"]
    # 非法 token 格式命中适配器的格式校验分支（NOT_FOUND）。
    response = api.get(
        f"/api/agent/v1/projects/{project['project_id']}/annotations/slides/slide_001/export-previews/not-a-valid-token",
    )
    assert response.status_code == 404, response.text
    error = _error_envelope(response)
    assert error["code"] == "NOT_FOUND", error


def test_request_validation_error_is_typed(api):
    """框架层请求校验错误（RequestValidationError）也统一为 Agent 信封——
    这是接入指南第 31 行承认的边界欠账，本次一并收口。"""
    response = api.post("/api/agent/v1/invoke", json={"capability_id": ""})
    assert response.status_code == 422
    error = _error_envelope(response)
    assert error["code"] == "VALIDATION_ERROR", error
    assert error["details"].get("errors"), error


def test_settings_llm_test_empty_payload_is_typed_422(api):
    """真实供应商演练 2026-10-24 发现：settings.*.test 适配器把自由载荷 dict
    直接传给期望 pydantic 模型的服务——llm/image 被 service 的 try 吞成静默
    success=false，tts 直接 500。修复后空载荷应得到类型化 422。"""
    detail = api.get("/api/agent/v1/capabilities/settings.llm.test")
    response = api.post("/api/agent/v1/invoke", json={
        "capability_id": "settings.llm.test",
        "expected_contract_revision": detail.json()["contract_revision"],
        "arguments": {"payload": {}},
    })
    assert response.status_code == 422, response.text
    error = _error_envelope(response)
    assert error["code"] == "VALIDATION_ERROR", error
    missing = {e["loc"][-1] for e in error["details"]["errors"] if e["type"] == "missing"}
    assert {"api_key", "model"} <= missing, error


def test_connections_test_unknown_id_is_typed_404(api):
    """真实供应商演练 2026-10-24 发现：connections.test 适配器调用不存在的
    服务函数恒 500。修复后未知连接应得到类型化 404。"""
    detail = api.get("/api/agent/v1/capabilities/connections.test")
    response = api.post("/api/agent/v1/invoke", json={
        "capability_id": "connections.test",
        "expected_contract_revision": detail.json()["contract_revision"],
        "arguments": {"connection_id": "mc_does_not_exist"},
    })
    assert response.status_code == 404, response.text
    error = _error_envelope(response)
    assert error["code"] == "NOT_FOUND", error
