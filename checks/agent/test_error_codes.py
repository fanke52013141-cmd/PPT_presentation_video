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


# ---------------------------------------------------------------------------
# 真实供应商演练 2026-10-24 待修项回归（f5c098a 之后的第二批修复）
# ---------------------------------------------------------------------------

def test_video_render_precondition_is_typed_409(api, monkeypatch):
    """前置门禁（音频未确认）不是服务器故障：409 + RENDER_PRECONDITION_FAILED。"""
    import pipeline_services
    from video_contracts import VideoRenderError

    project = api.post("/api/agent/v1/invoke", json={
        "capability_id": "project.create",
        "expected_contract_revision": api.get("/api/agent/v1/capabilities/project.create").json()["contract_revision"],
        "arguments": {"name": "渲染前置门禁项目"},
    }).json()["project"]

    def _raising_services(db, project_id):
        class _Services:
            def render_video(self):
                raise VideoRenderError(400, "请先在“旁白与音频”步骤试听并确认音频，再开始视频渲染。")
        return _Services()

    monkeypatch.setattr(pipeline_services, "get_project_pipeline_services", _raising_services)
    detail = api.get("/api/agent/v1/capabilities/video.render")
    response = api.post("/api/agent/v1/invoke", json={
        "capability_id": "video.render",
        "expected_contract_revision": detail.json()["contract_revision"],
        "arguments": {"project_id": project["project_id"]},
    })
    assert response.status_code == 409, response.text
    error = _error_envelope(response)
    assert error["code"] == "RENDER_PRECONDITION_FAILED", error
    assert error["repair_actions"] == [{"action": "confirm_audio_before_render"}], error


def test_agent_http_error_maps_dict_detail_to_typed_code():
    """Web 层 dict-detail HTTPException（revision_conflict）拆为类型化码 + details。"""
    from agent_api.domain_routes.common import agent_http_error

    error = agent_http_error(409, {"code": "revision_conflict", "current_revision": 0})
    assert error.code == "REVISION_CONFLICT"
    assert error.status_code == 409
    assert error.details == {"current_revision": 0}
    assert "revision_conflict" in error.message


def test_style_output_shape_coercion():
    """新模型把数组字段输出成标量时，归一后应通过严格校验而非 500。"""
    from project_profile_service import (
        _coerce_generated_style_shapes,
        validate_generated_image_style_model_output,
    )

    raw = {
        "style_name": "温暖扁平插画",
        "style_summary": "暖色治愈系",
        "visual_language": "整体暖色调，米白底，琥珀金点缀",
        "negative_prompt_rules": "不要使用渐变背景",
        "sample_reference_image_prompts": None,
    }
    coerced = _coerce_generated_style_shapes(raw)
    validated = validate_generated_image_style_model_output(coerced)
    assert validated["negative_prompt_rules"] == ["不要使用渐变背景"]
    assert validated["sample_reference_image_prompts"] == []
    assert validated["visual_language"] == {"overall": "整体暖色调，米白底，琥珀金点缀"}


def test_mask_result_update_rolls_back_manifest_on_build_failure(api, monkeypatch):
    """P1 回归：终稿保存先写 manifest 再构建资产，构建失败必须回滚写入，
    否则空/非法 manifest 落盘且项目无法经 API 恢复（真实供应商演练
    2026-10-24 两次踩中）。"""
    import json as jsonlib
    from pathlib import Path

    import mask_manifest_service
    import pytest

    project = api.post("/api/agent/v1/invoke", json={
        "capability_id": "project.create",
        "expected_contract_revision": api.get("/api/agent/v1/capabilities/project.create").json()["contract_revision"],
        "arguments": {"name": "Mask回滚测试项目"},
    }).json()["project"]

    from database import Project, SessionLocal
    with SessionLocal() as db:
        run_dir = Path(db.get(Project, project["project_id"]).run_dir)

    previous_manifest = {
        "version": "reveal_v1",
        "canvas": {"width": 1920, "height": 1080, "background": "#FEFDF9", "subtitle_safe_y": 1080},
        "slides": [{"slide_id": "slide_001", "groups": []}],
    }
    manifest_path = run_dir / "reveal_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(jsonlib.dumps(previous_manifest, ensure_ascii=False), encoding="utf-8")

    def _failing_build(project_obj):
        raise RuntimeError("构建精确 Mask 素材失败: simulated remotion crash")

    monkeypatch.setattr(mask_manifest_service, "build_current_reveal_assets", _failing_build)

    changed_manifest = dict(previous_manifest, slides=[{"slide_id": "slide_001", "groups": [{"x": 1}]}])
    detail = api.get("/api/agent/v1/capabilities/mask.result.update")
    with pytest.raises(RuntimeError):
        api.post("/api/agent/v1/invoke", json={
            "capability_id": "mask.result.update",
            "expected_contract_revision": detail.json()["contract_revision"],
            "arguments": {"project_id": project["project_id"], "payload": changed_manifest, "build_assets": True},
        })

    on_disk = jsonlib.loads(manifest_path.read_text(encoding="utf-8"))
    assert on_disk == previous_manifest, "构建失败后 manifest 必须回滚到保存前状态"
