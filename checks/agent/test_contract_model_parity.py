"""Keep the Agent contract in lockstep with internal service models.

These guards fail whenever a field is added to an internal project model
without a deliberate decision about its Agent-facing exposure.  Adding a new
internal field requires registering it in the mapping tables below — mapped
to a contract field name, or ``None`` when it is intentionally hidden from
Agents.  When a field gains contract exposure, also bump the capability
version in ``agent_contract/capabilities.py`` and regenerate
``docs/agent/capability-matrix.md`` via
``python scripts/generate_agent_contracts.py``.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


# project_service.ProjectCreate field -> agent_contract ProjectCreateRequest field.
# None = intentionally not exposed to Agents.
_CREATE_FIELD_MAP = {
    "name": "name",
    "description": "description",
    "ai_mode": "automation_mode",
    "canvas_profile": "canvas_profile",
    "review_policy": "review_policy",
    "manual_pause_steps": None,      # UI-only, derived from automation_mode
    "image_style_template": None,     # UI-only, Step 3 image-style selection
    "mask_enabled": "mask_enabled",
    "creation_config_package_id": None,  # canonical internal alias; Agent uses short name
    "creation_config_version": None,
    "creation_config_overrides": None,
    "config_package_id": "config_package_id",
    "config_package_version": "config_package_version",
    "config_overrides": "config_overrides",
}

# project_service project payload key -> agent_contract ProjectSummary field.
# None = intentionally not exposed to Agents.
_SUMMARY_FIELD_MAP = {
    "id": "project_id",
    "name": "name",
    "description": "description",
    "canvas_profile": "canvas_profile",
    "ai_mode": "ai_mode",
    "current_step": "current_step",
    "status": "status",
    "step_status": "step_status",
    "revision": "revision",
    "review_policy": "review_policy",
    "manual_pause_steps": None,
    "image_style_template": None,
    "mask_enabled": "mask_enabled",
    "creation_config": "creation_config",
    "created_at": "created_at",
}


def test_project_create_request_covers_internal_fields():
    from project_service import ProjectCreate
    from agent_contract.models import ProjectCreateRequest

    internal_fields = set(ProjectCreate.model_fields)
    unknown = internal_fields - set(_CREATE_FIELD_MAP)
    assert not unknown, (
        "project_service.ProjectCreate 新增了字段但未决定 Agent 契约暴露方式: "
        f"{sorted(unknown)}。请在 checks/agent/test_contract_model_parity.py 的 "
        "_CREATE_FIELD_MAP 中登记（映射到 agent_contract.models.ProjectCreateRequest "
        "的字段名，或 None 表示有意不暴露）；若新增契约字段，请同步 "
        "agent_api/routes.py 的 agent_create_project、agent_contract/capabilities.py "
        "的 capability 版本号，并运行 scripts/generate_agent_contracts.py。"
    )
    for internal, contract in _CREATE_FIELD_MAP.items():
        assert internal in internal_fields, (
            f"内部字段 {internal} 已不存在于 ProjectCreate，请清理 _CREATE_FIELD_MAP"
        )
        if contract is None:
            continue
        assert contract in ProjectCreateRequest.model_fields, (
            f"映射声明内部字段 {internal} 对应契约字段 {contract}，但 "
            "ProjectCreateRequest 中不存在该字段，请同步 agent_contract/models.py"
        )


def test_project_summary_covers_internal_payload_keys():
    from project_service import ProjectService
    from agent_contract.models import ProjectSummary

    # The service layer composes project dicts from a fixed key set shared by
    # create/list/get; verify each registered key maps to a real summary field.
    for internal, contract in _SUMMARY_FIELD_MAP.items():
        if contract is None:
            continue
        assert contract in ProjectSummary.model_fields, (
            f"映射声明内部键 {internal} 对应契约字段 {contract}，但 ProjectSummary "
            "中不存在该字段，请同步 agent_contract/models.py 与 agent_api/routes.py"
        )
    assert "mask_enabled" in ProjectSummary.model_fields


def _mock_project(**overrides):
    base = {
        "id": "p_parity",
        "name": "parity",
        "description": "d",
        "canvas_profile": "landscape_16_9",
        "ai_mode": "auto",
        "current_step": 1,
        "status": "active",
        "revision": 3,
        "review_policy": "none",
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    base.update(overrides)
    ns = SimpleNamespace(**base)
    ns.get_step_status = lambda: {"step_1": "done"}
    return ns


class TestProjectSummaryMaskMode:
    def test_mask_disabled_is_reflected(self):
        from agent_api.routes import _project_summary

        summary = _project_summary(_mock_project(mask_enabled=0))
        assert summary.mask_enabled is False

    def test_mask_enabled_is_reflected(self):
        from agent_api.routes import _project_summary

        summary = _project_summary(_mock_project(mask_enabled=1))
        assert summary.mask_enabled is True

    def test_missing_mask_column_defaults_to_enabled(self):
        from agent_api.routes import _project_summary

        project = _mock_project()
        summary = _project_summary(project)
        assert summary.mask_enabled is True


@pytest.fixture(scope="module")
def api_client():
    try:
        from fastapi.testclient import TestClient
        import server

        return TestClient(server.app)
    except Exception as e:
        pytest.skip(f"Cannot create TestClient (server deps not available): {e}")


class TestAgentCreateProjectMaskMode:
    def test_create_with_mask_disabled(self, api_client):
        resp = api_client.post(
            "/api/agent/v1/projects",
            json={
                "name": "Parity Mask Off Test",
                "mask_enabled": False,
            },
        )
        assert resp.status_code == 200, resp.text
        project = resp.json()["project"]
        assert project["mask_enabled"] is False

        get_resp = api_client.get(f"/api/agent/v1/projects/{project['project_id']}")
        assert get_resp.status_code == 200
        assert get_resp.json()["project"]["mask_enabled"] is False

    def test_create_defaults_to_mask_enabled(self, api_client):
        resp = api_client.post(
            "/api/agent/v1/projects",
            json={"name": "Parity Mask Default Test"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["project"]["mask_enabled"] is True
