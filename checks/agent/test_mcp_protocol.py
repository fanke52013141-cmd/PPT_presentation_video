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

import json
import pytest
from unittest.mock import MagicMock, patch

from agent_contract.versions import AGENT_API_VERSION, CONTRACT_VERSION
from mcp_server.server import MCPServer, MCP_PROTOCOL_VERSION, SERVER_NAME


def _make_server_with_matching_contract() -> MCPServer:
    """Create an MCPServer whose client returns a contract matching the local registry."""
    server = MCPServer(base_url="http://mock")
    mock_client = MagicMock()
    mock_client.get_meta.return_value = {
        "contract_hash": CONTRACT_VERSION,
        "agent_api_version": AGENT_API_VERSION,
    }
    server._client = mock_client
    return server


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
    """Test the contract negotiation logic during initialize."""

    def test_hash_mismatch_major_version_returns_error(self):
        """Hash mismatch + major version difference → error code -32000."""
        server = _make_server_with_mismatched_contract(
            api_hash="aaaa0000bbbb0000",
            api_version="2.0.0",
        )
        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 100, "method": "initialize", "params": {}
        })
        assert "error" in resp
        assert resp["error"]["code"] == -32000
        assert "Contract mismatch" in resp["error"]["message"]
        assert "Major version mismatch" in resp["error"]["message"]

    def test_hash_mismatch_minor_version_succeeds_with_warning(self):
        """Hash mismatch + minor version difference → success with mismatchDetail."""
        server = _make_server_with_mismatched_contract(
            api_hash="cccc0000dddd0000",
            api_version="1.2.0",
        )
        result = server.handle_request({
            "jsonrpc": "2.0", "id": 101, "method": "initialize", "params": {}
        })["result"]
        assert result["serverInfo"]["contractMatch"] is True
        assert "mismatchDetail" in result["serverInfo"]
        assert "Minor/patch difference" in result["serverInfo"]["mismatchDetail"]

    def test_hash_mismatch_patch_version_succeeds_with_warning(self):
        """Hash mismatch + patch version difference → success with mismatchDetail."""
        server = _make_server_with_mismatched_contract(
            api_hash="eeee0000ffff0000",
            api_version="1.1.5",
        )
        result = server.handle_request({
            "jsonrpc": "2.0", "id": 102, "method": "initialize", "params": {}
        })["result"]
        assert result["serverInfo"]["contractMatch"] is True
        assert "mismatchDetail" in result["serverInfo"]

    def test_api_unreachable_returns_error(self):
        """API service unreachable → error code -32000."""
        server = _make_server_with_unreachable_api()
        resp = server.handle_request({
            "jsonrpc": "2.0", "id": 103, "method": "initialize", "params": {}
        })
        assert "error" in resp
        assert resp["error"]["code"] == -32000
        assert "Cannot reach API service" in resp["error"]["message"]

    def test_contract_check_disabled_bypasses_negotiation(self, monkeypatch):
        """PPT_MCP_CONTRACT_CHECK=0 → bypass negotiation, contractMatch is None."""
        monkeypatch.setenv("PPT_MCP_CONTRACT_CHECK", "0")
        server = MCPServer(base_url="http://mock")
        # Client should not be called at all
        mock_client = MagicMock()
        server._client = mock_client

        result = server.handle_request({
            "jsonrpc": "2.0", "id": 104, "method": "initialize", "params": {}
        })["result"]
        assert result["serverInfo"]["contractMatch"] is None
        mock_client.get_meta.assert_not_called()

    def test_tools_call_blocked_after_mismatch(self):
        """tools/call should return isError when contract mismatch was detected."""
        server = _make_server_with_mismatched_contract(
            api_hash="dead0000", api_version="2.0.0",
        )
        # Trigger negotiation via initialize (will fail)
        init_resp = server.handle_request({
            "jsonrpc": "2.0", "id": 105, "method": "initialize", "params": {}
        })
        assert "error" in init_resp  # Confirm mismatch was detected

        # Now try tools/call
        call_result = server.handle_request({
            "jsonrpc": "2.0", "id": 106,
            "method": "tools/call",
            "params": {"name": "ppt_project_list", "arguments": {}}
        })["result"]
        assert call_result["isError"] is True
        assert "blocked" in call_result["content"][0]["text"].lower()

    def test_tools_call_allowed_after_minor_mismatch(self):
        """tools/call should work when contract match is True (minor difference)."""
        server = _make_server_with_mismatched_contract(
            api_hash="minor00000", api_version="1.1.0",
        )
        init_resp = server.handle_request({
            "jsonrpc": "2.0", "id": 107, "method": "initialize", "params": {}
        })
        assert "result" in init_resp  # Initialize succeeded

        # tools/call should proceed (mock returns empty project list)
        server._client.list_projects.return_value = {"projects": [], "total": 0}
        call_result = server.handle_request({
            "jsonrpc": "2.0", "id": 108,
            "method": "tools/call",
            "params": {"name": "ppt_project_list", "arguments": {}}
        })["result"]
        assert call_result["isError"] is False

    def test_initialize_includes_api_contract_fields_on_success(self):
        """Successful negotiation includes apiContractHash and apiAgentApiVersion."""
        server = _make_server_with_matching_contract()
        result = server.handle_request({
            "jsonrpc": "2.0", "id": 109, "method": "initialize", "params": {}
        })["result"]
        assert "apiContractHash" in result["serverInfo"]
        assert "apiAgentApiVersion" in result["serverInfo"]
        assert result["serverInfo"]["apiAgentApiVersion"] == AGENT_API_VERSION


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
        mock_client.list_projects.return_value = {"projects": [], "total": 0}
        server._client = mock_client

        result = server.handle_request({
            "jsonrpc": "2.0", "id": 5,
            "method": "tools/call",
            "params": {"name": "ppt_project_list", "arguments": {"limit": 5}}
        })["result"]
        assert result["isError"] is False
        assert isinstance(result["content"], list)
        mock_client.list_projects.assert_called_once()

    def test_tool_call_with_agent_error(self):
        """AgentClientError should be caught and returned as error content."""
        from agent_client.client import AgentClientError

        server = MCPServer(base_url="http://mock")
        mock_client = MagicMock()
        mock_client.get_project.side_effect = AgentClientError("Not found", status_code=404)
        server._client = mock_client

        result = server.handle_request({
            "jsonrpc": "2.0", "id": 6,
            "method": "tools/call",
            "params": {"name": "ppt_project_get", "arguments": {"project_id": "xxx"}}
        })["result"]
        # Should NOT be an MCP-level error (isError=False), but the text describes the API error
        assert "API Error" in result["content"][0]["text"] or "404" in result["content"][0]["text"]


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
