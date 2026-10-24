"""Tests for MCP Server JSON-RPC protocol handling.

Tests the MCPServer class directly without stdio I/O:
- initialize handshake
- tools/list format
- tools/call dispatch
- resources/list and resources/read
- Error responses
- Notification handling
"""

from __future__ import annotations

from unittest.mock import MagicMock

from agent_contract.versions import AGENT_API_VERSION, CONTRACT_VERSION
from mcp_server.server import MCPServer, MCP_PROTOCOL_VERSION, SERVER_NAME


def _make_server_with_matching_contract() -> MCPServer:
    """Create an MCPServer whose client returns a contract matching the local registry."""
    server = MCPServer(base_url="http://mock")
    mock_client = MagicMock()
    mock_client.get_meta.return_value = {
        "contract_hash": CONTRACT_VERSION,
        "agent_api_version": AGENT_API_VERSION,
        "bootstrap_version": "1",
    }
    server._client = mock_client
    return server


def _relative_version(*, minor_offset: int = 0, patch_offset: int = 0) -> str:
    """Return a version derived from AGENT_API_VERSION with a fixed offset.

    Keeps the mocked remote version stable relative to the real registry
    version, so contract-negotiation tests do not break whenever
    AGENT_API_VERSION is bumped.
    """
    major, minor, patch = (int(part) for part in AGENT_API_VERSION.split("."))
    return f"{major}.{minor + minor_offset}.{patch + patch_offset}"


def test_mcp_prefers_agent_api_key_environment(monkeypatch):
    """MCP must use the same preferred authentication variable as AgentClient."""
    monkeypatch.setenv("PPT_AGENT_API_KEY", "agent-key")
    monkeypatch.setenv("PPT_APP_TOKEN", "legacy-key")

    server = MCPServer(base_url="http://mock")

    assert server.app_token == "agent-key"


class TestInitialize:
    """Test the MCP initialize handshake."""

    def test_initialize_returns_protocol_version(self):
        server = _make_server_with_matching_contract()
        resp = server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        })
        assert resp is not None
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 1
        result = resp["result"]
        assert result["protocolVersion"] == MCP_PROTOCOL_VERSION
        assert result["serverInfo"]["name"] == SERVER_NAME

    def test_initialize_includes_capabilities(self):
        server = _make_server_with_matching_contract()
        result = server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
        })["result"]
        assert "tools" in result["capabilities"]
        assert "resources" in result["capabilities"]

    def test_initialize_includes_contract_hash(self):
        server = _make_server_with_matching_contract()
        result = server.handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}
        })["result"]
        assert "contractHash" in result["serverInfo"]
        assert len(result["serverInfo"]["contractHash"]) > 0
        assert result["serverInfo"]["contractMatch"] is True
        assert result["serverInfo"]["writeAllowed"] is True


def _make_server_with_mismatched_contract(
    api_hash: str = "dead0000beef0000",
    api_version: str = "2.0.0",
) -> MCPServer:
    """Create an MCPServer whose client returns a mismatched contract."""
    server = MCPServer(base_url="http://mock")
    mock_client = MagicMock()
    mock_client.get_meta.return_value = {
        "contract_hash": api_hash,
        "agent_api_version": api_version,
    }
    server._client = mock_client
    return server


def _make_server_with_unreachable_api() -> MCPServer:
    """Create an MCPServer whose client raises on get_meta."""
    server = MCPServer(base_url="http://mock")
    mock_client = MagicMock()
    mock_client.get_meta.side_effect = ConnectionError("Connection refused")
    server._client = mock_client
    return server


class TestContractNegotiation:
    def test_new_business_contract_does_not_require_local_update(self):
        server = _make_server_with_mismatched_contract(api_hash="new", api_version="99.0.0")
        server._client.get_meta.return_value["bootstrap_version"] = "1"
        result = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert result["result"]["serverInfo"]["writeAllowed"] is True
        assert "current schemas" in result["result"]["serverInfo"]["mismatchDetail"]

    def test_unsupported_bootstrap_requires_upgrade(self):
        server = _make_server_with_matching_contract()
        server._client.get_meta.return_value["bootstrap_version"] = "unsupported"
        response = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert response["error"]["code"] == -32000
        server._client.invoke.assert_not_called()

    def test_api_unreachable_returns_error(self):
        server = _make_server_with_unreachable_api()
        response = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        assert response["error"]["code"] == -32000
        assert "Cannot reach API service" in response["error"]["message"]

    def test_named_write_requires_initialize(self):
        server = MCPServer(base_url="http://mock")
        result = server._handle_tools_call({"name": "ppt_project_create", "arguments": {"name": "blocked"}})
        assert result["isError"] is True

    def test_named_write_pins_shown_contract_after_initialize(self):
        from agent_contract.capabilities import get_capability
        from agent_contract.discovery import describe_capability
        server = _make_server_with_matching_contract()
        server._client.invoke.return_value = {"project": {"project_id": "p1", "name": "created"}}
        server._handle_initialize({})
        result = server._handle_tools_call({"name": "ppt_project_create", "arguments": {"name": "created"}})
        assert result["isError"] is False
        server._client.invoke.assert_called_once_with("project.create", {"name": "created"},
            expected_contract_revision=describe_capability(get_capability("project.create"))["contract_revision"])


class TestToolsList:
    """Test tools/list method."""

    def test_returns_tool_array(self):
        server = MCPServer(base_url="http://mock")
        result = server.handle_request({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}
        })["result"]
        assert "tools" in result
        assert isinstance(result["tools"], list)
        assert len(result["tools"]) >= 17  # at least 17 capabilities

    def test_each_tool_has_required_fields(self):
        server = MCPServer(base_url="http://mock")
        tools = server.handle_request({
            "jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}
        })["result"]["tools"]
        for tool in tools:
            assert "name" in tool
            assert "description" in tool
            assert "inputSchema" in tool


class TestToolsCall:
    """Test tools/call method dispatch."""

    def test_unknown_tool_returns_error_content(self):
        server = MCPServer(base_url="http://mock")
        result = server.handle_request({
            "jsonrpc": "2.0", "id": 4,
            "method": "tools/call",
            "params": {"name": "ppt_nonexistent", "arguments": {}}
        })["result"]
        assert result["isError"] is True
        assert "Unknown tool" in result["content"][0]["text"]

    def test_known_tool_dispatches_to_client(self):
        """Verify a known tool name invokes the AgentClient."""
        server = MCPServer(base_url="http://mock")
        # Mock the client to avoid actual HTTP
        mock_client = MagicMock()
        mock_client.invoke.return_value = {"projects": [], "total": 0}
        server._client = mock_client

        result = server.handle_request({
            "jsonrpc": "2.0", "id": 5,
            "method": "tools/call",
            "params": {"name": "ppt_project_list", "arguments": {"limit": 5}}
        })["result"]
        assert result["isError"] is False
        assert isinstance(result["content"], list)
        mock_client.invoke.assert_called_once()

    def test_tool_call_with_agent_error(self):
        """AgentClientError should be caught and returned as error content."""
        from agent_client.client import AgentClientError

        server = MCPServer(base_url="http://mock")
        mock_client = MagicMock()
        mock_client.invoke.side_effect = AgentClientError("Not found", status_code=404, code="PROJECT_NOT_FOUND")
        server._client = mock_client

        result = server.handle_request({
            "jsonrpc": "2.0", "id": 6,
            "method": "tools/call",
            "params": {"name": "ppt_project_get", "arguments": {"project_id": "xxx"}}
        })["result"]
        # Should NOT be an MCP-level error (isError=False), but the text describes the API error
        assert result["isError"] is True
        assert "PROJECT_NOT_FOUND" in result["content"][0]["text"]


class TestResourcesList:
    """Test resources/list method."""

    def test_returns_empty_resources(self):
        server = MCPServer(base_url="http://mock")
        result = server.handle_request({
            "jsonrpc": "2.0", "id": 7, "method": "resources/list", "params": {}
        })["result"]
        assert "resources" in result
        assert isinstance(result["resources"], list)


class TestResourcesTemplates:
    """Test resources/templates/list method."""

    def test_returns_templates(self):
        server = MCPServer(base_url="http://mock")
        result = server.handle_request({
            "jsonrpc": "2.0", "id": 8, "method": "resources/templates/list", "params": {}
        })["result"]
        assert "resourceTemplates" in result
        assert len(result["resourceTemplates"]) >= 5

    def test_templates_have_uri_scheme(self):
        server = MCPServer(base_url="http://mock")
        templates = server.handle_request({
            "jsonrpc": "2.0", "id": 9, "method": "resources/templates/list", "params": {}
        })["result"]["resourceTemplates"]
        for t in templates:
            assert t["uriTemplate"].startswith("ppt://")


class TestResourcesRead:
    """Test resources/read method."""

    def test_read_unknown_uri(self):
        server = MCPServer(base_url="http://mock")
        mock_client = MagicMock()
        server._client = mock_client

        result = server.handle_request({
            "jsonrpc": "2.0", "id": 10,
            "method": "resources/read",
            "params": {"uri": "http://unknown"}
        })["result"]
        assert "contents" in result
        assert "Unknown resource URI" in result["contents"][0]["text"]

    def test_read_summary_resource(self):
        server = MCPServer(base_url="http://mock")
        mock_client = MagicMock()
        mock_client.get_project.return_value = {"project": {"project_id": "p1", "name": "Test"}}
        server._client = mock_client

        result = server.handle_request({
            "jsonrpc": "2.0", "id": 11,
            "method": "resources/read",
            "params": {"uri": "ppt://projects/p1/summary"}
        })["result"]
        assert "contents" in result
        mock_client.get_project.assert_called_once_with("p1")


class TestProtocolHandling:
    """Test JSON-RPC protocol edge cases."""

    def test_ping_returns_empty(self):
        server = MCPServer(base_url="http://mock")
        result = server.handle_request({
            "jsonrpc": "2.0", "id": 20, "method": "ping", "params": {}
        })
        assert result["result"] == {}

    def test_notification_returns_none(self):
        """Notifications (no id) should return None."""
        server = MCPServer(base_url="http://mock")
        result = server.handle_request({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        })
        assert result is None

    def test_unknown_method_returns_error(self):
        server = MCPServer(base_url="http://mock")
        result = server.handle_request({
            "jsonrpc": "2.0", "id": 21, "method": "unknown/method", "params": {}
        })
        assert "error" in result
        assert "Unknown method" in result["error"]["message"]

    def test_request_with_string_id(self):
        """String IDs should be preserved in responses."""
        server = MCPServer(base_url="http://mock")
        result = server.handle_request({
            "jsonrpc": "2.0", "id": "req-abc", "method": "ping", "params": {}
        })
        assert result["id"] == "req-abc"


# ---------------------------------------------------------------------------
# 命名工具指纹绑定（审查 2026-10-24 P2-3）
# ---------------------------------------------------------------------------

class TestNamedToolRevisionBinding:
    def test_handler_binds_revision_at_registration(self, monkeypatch):
        """命名工具发送注册时的 contract_revision，而非调用时现算的最新值。"""
        from agent_contract.capabilities import get_capability
        from agent_contract.discovery import describe_capability
        from mcp_server import tools as mcp_tools

        cap = get_capability("project.list")
        bound = describe_capability(cap)["contract_revision"]
        handler = mcp_tools.get_tool_handler(cap.mcp_tool_name)

        captured = {}

        class _Client:
            def invoke(self, capability_id, args, *, expected_contract_revision):
                captured["revision"] = expected_contract_revision
                return {"projects": [], "total": 0}

        # 模拟服务端契约变化：调用时现算会拿到新指纹，绑定语义仍发送旧指纹。
        monkeypatch.setattr(
            "agent_contract.discovery.describe_capability",
            lambda c: {**describe_capability(c), "contract_revision": "changed-revision"},
        )
        handler({}, _Client())
        assert captured["revision"] == bound

    def test_handler_cache_returns_same_closure(self):
        from agent_contract.capabilities import get_capability
        from agent_contract.discovery import describe_capability
        from mcp_server import tools as mcp_tools

        tool_name = get_capability("project.list").mcp_tool_name
        mcp_tools._handler_cache.pop(tool_name, None)
        assert mcp_tools.get_tool_handler(tool_name) is mcp_tools.get_tool_handler(tool_name)
        mcp_tools._handler_cache.pop(tool_name, None)
