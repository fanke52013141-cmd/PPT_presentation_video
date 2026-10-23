"""Real isolated business operations through the current-contract bootstrap."""

import json
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from agent_contract.capabilities import CAPABILITIES, get_capability
from agent_contract.discovery import describe_capability


@pytest.fixture(scope="module")
def api():
    # conftest has selected an isolated database/runs directory before this import.
    import server
    return TestClient(server.app, client=("agent-dynamic-" + uuid.uuid4().hex, 50000))


def invoke(api, capability_id, arguments, revision=None):
    if revision is None:
        detail = api.get(f"/api/agent/v1/capabilities/{capability_id}")
        assert detail.status_code == 200, detail.text
        revision = detail.json()["contract_revision"]
    return api.post("/api/agent/v1/invoke", json={
        "capability_id": capability_id, "expected_contract_revision": revision,
        "arguments": arguments,
    })


def test_discovery_is_paginated_and_searchable(api):
    result = api.get("/api/agent/v1/capabilities", params={"domain": "project", "limit": 2}).json()
    assert len(result["items"]) == 2
    assert result["next_offset"] == 2
    assert all(item["domain"] == "project" for item in result["items"])
    assert "input_schema" not in result["items"][0]
    assert api.get("/api/agent/v1/capabilities/no.such.capability").status_code == 404


def test_bootstrap_openapi_describes_required_revision(api):
    spec = api.get("/api/agent/v1/openapi.json").json()
    operation = spec["paths"]["/api/agent/v1/invoke"]["post"]
    assert operation["requestBody"]["required"] is True
    schema = spec["components"]["schemas"]["InvokeRequest"]
    assert "expected_contract_revision" in schema["required"]
    assert schema["additionalProperties"] is False


def test_project_article_update_and_idempotency(api):
    arguments = {"name": "Dynamic Agent test", "idempotency_key": uuid.uuid4().hex}
    first = invoke(api, "project.create", arguments)
    assert first.status_code == 200, first.text
    project = first.json()["project"]
    pid = project["project_id"]
    replay = invoke(api, "project.create", arguments)
    assert replay.json()["project"]["project_id"] == pid
    assert replay.headers.get("x-agent-idempotency-replay") == "true"
    source = invoke(api, "source.set", {"project_id": pid, "content": "# 测试文章\n\n用于验证 Agent 导入和读取。"})
    assert source.status_code == 200, source.text
    read = invoke(api, "project.get", {"project_id": pid})
    assert read.json()["has_article"] is True
    revision = read.json()["project"]["revision"]
    update = invoke(api, "project.update", {"project_id": pid, "description": "Updated via invoke", "expected_revision": revision})
    assert update.status_code == 200, update.text
    assert update.json()["project"]["description"] == "Updated via invoke"
    assert invoke(api, "project.update", {"project_id": pid, "name": "Stale", "expected_revision": revision}).status_code == 409


def test_changed_contract_never_executes(api, monkeypatch):
    from agent_api import routes
    def forbidden(**kwargs):
        pytest.fail("Business handler must not execute")
    monkeypatch.setattr(routes, "agent_create_project", forbidden)
    result = invoke(api, "project.create", {"name": "Do not create"}, revision="outdated")
    assert result.status_code == 409
    assert result.json()["error"]["code"] == "CONTRACT_CHANGED"
    assert result.json()["error"]["details"]["executed"] is False


@pytest.mark.parametrize("arguments", [
    {"name": "typo", "unknown_option": True}, {},
])
def test_invalid_input_rejected_before_business(api, monkeypatch, arguments):
    from agent_api import routes
    monkeypatch.setattr(routes, "agent_create_project", lambda **kw: pytest.fail("Must not execute"))
    assert invoke(api, "project.create", arguments).status_code == 422


def test_source_rejects_ambiguous_input(api):
    response = invoke(api, "source.set", {"project_id": "missing", "content": "text", "topic": "topic"})
    assert response.status_code == 422


def test_unknown_and_binary_capabilities_fail_explicitly(api):
    assert invoke(api, "unknown.operation", {}, revision="unknown").status_code == 404
    binary = invoke(api, "image.get", {"project_id": "missing", "slide_id": "slide_001"})
    assert binary.status_code == 422
    assert binary.json()["error"]["code"] == "UNSUPPORTED_TRANSPORT"


def test_behavior_only_change_changes_revision():
    cap = get_capability("project.get")
    assert describe_capability(cap)["contract_revision"] != describe_capability(
        replace(cap, behavior_version="changed"))["contract_revision"]


def test_every_json_capability_has_explicit_handler():
    from agent_api.dispatch import HANDLERS
    from agent_api import routes
    assert set(HANDLERS) == {cap.id for cap in CAPABILITIES if describe_capability(cap)["invocable"]}
    assert all(callable(getattr(routes, name)) for name in HANDLERS.values())


def test_runtime_addition_needs_no_client_branch(api, monkeypatch):
    from agent_api import routes
    from agent_api.dispatch import HANDLERS
    from agent_client.client import AgentClient
    cap = replace(get_capability("project.get"), id="test.new_read", mcp_tool_name="ppt_new_read")
    monkeypatch.setattr("agent_contract.capabilities.CAPABILITIES", CAPABILITIES + [cap])
    monkeypatch.setattr("agent_api.discovery.CAPABILITIES", CAPABILITIES + [cap])
    monkeypatch.setitem(HANDLERS, cap.id, "agent_get_project")
    monkeypatch.setattr(routes, "agent_get_project", lambda project_id, db: {
        "project": {"project_id": project_id, "name": "new", "description": "", "canvas_profile": "landscape_16_9",
                    "ai_mode": "auto", "current_step": 1, "status": "active", "step_status": {}}})

    class LocalClient(AgentClient):
        def _request(self, method, path, body=None, params=None, timeout=None):
            response = api.request(method, path, json=body, params=params)
            assert response.status_code == 200, response.text
            return response.json()
    client = LocalClient()
    assert client.describe(cap.id)["id"] == cap.id
    assert client.invoke(cap.id, {"project_id": "new-project"})["project"]["name"] == "new"


def test_fixed_mcp_tools_work_despite_local_mismatch(monkeypatch):
    from mcp_server.server import MCPServer
    class Client:
        def describe(self, capability_id):
            return {"id": capability_id, "contract_revision": "runtime"}
    server = MCPServer()
    server._client = Client()
    server._contract_state = {"match": False, "write_allowed": False}
    result = server._handle_tools_call({"name": "ppt_capability_describe", "arguments": {"capability_id": "new.cap"}})
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"])["contract_revision"] == "runtime"


def test_invoke_uses_capability_scope_not_outer_post(api):
    from database import SessionLocal
    from account_service import create_agent_token
    with SessionLocal() as db:
        token = create_agent_token(db, "default", scopes=["project:read"])["token"]
    headers = {"Authorization": "Bearer " + token}
    args = {"capability_id": "project.list", "arguments": {},
            "expected_contract_revision": describe_capability(get_capability("project.list"))["contract_revision"]}
    read = api.post("/api/agent/v1/invoke", json=args, headers=headers)
    assert read.status_code == 200, read.text
    args.update(capability_id="project.create", arguments={"name": "Forbidden"},
                expected_contract_revision=describe_capability(get_capability("project.create"))["contract_revision"])
    write = api.post("/api/agent/v1/invoke", json=args, headers=headers)
    assert write.status_code == 403
    assert write.json()["error"]["code"] == "FORBIDDEN"


def test_other_account_cannot_read_project(api):
    from database import SessionLocal
    from account_service import create_account, create_agent_token
    created = invoke(api, "project.create", {"name": "Private project"})
    assert created.status_code == 200
    pid = created.json()["project"]["project_id"]
    with SessionLocal() as db:
        account = create_account(db, name="Other account " + uuid.uuid4().hex[:6])
        token = create_agent_token(db, account["id"], scopes=["project:read"])["token"]
    response = api.post("/api/agent/v1/invoke", headers={"Authorization": "Bearer " + token}, json={
        "capability_id": "project.get", "arguments": {"project_id": pid},
        "expected_contract_revision": describe_capability(get_capability("project.get"))["contract_revision"],
    })
    assert response.status_code == 404


def test_cli_discovery_and_invoke_preserve_contract(monkeypatch, capsys, tmp_path):
    from cli.pptctl import main
    from unittest.mock import MagicMock
    client = MagicMock()
    client.invoke.return_value = {"project": {"project_id": "p1"}}
    monkeypatch.setattr("cli.discovery.AgentClient", lambda **kwargs: client)
    file = tmp_path / "arguments.json"
    file.write_text(json.dumps({"name": "动态项目"}), encoding="utf-8")
    main(["invoke", "project.create", "--contract-revision", "observed", "--arguments-file", str(file)])
    client.invoke.assert_called_once_with("project.create", {"name": "动态项目"}, expected_contract_revision="observed")
    assert json.loads(capsys.readouterr().out)["project"]["project_id"] == "p1"


def test_cli_keeps_structured_api_error(monkeypatch, capsys):
    from cli.pptctl import main
    from agent_client.client import AgentClientError
    from unittest.mock import MagicMock
    client = MagicMock()
    client.invoke.side_effect = AgentClientError("Refresh schema", 409, {"executed": False}, "CONTRACT_CHANGED")
    monkeypatch.setattr("cli.discovery.AgentClient", lambda **kwargs: client)
    with pytest.raises(SystemExit) as error:
        main(["invoke", "project.create", "--contract-revision", "stale", "--arguments", "{}"])
    assert error.value.code == 1
    output = json.loads(capsys.readouterr().err)
    assert output["error"]["code"] == "CONTRACT_CHANGED"
    assert output["error"]["details"]["executed"] is False


def test_explicit_empty_revision_is_never_silently_refreshed():
    from agent_client.client import AgentClient
    from unittest.mock import MagicMock
    client = AgentClient()
    client._request = MagicMock()
    with pytest.raises(ValueError, match="non-empty"):
        client.invoke("project.create", {"name": "Must not execute"}, expected_contract_revision="")
    client._request.assert_not_called()
