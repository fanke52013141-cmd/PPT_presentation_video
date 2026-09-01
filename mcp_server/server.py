"""MCP Server — JSON-RPC 2.0 over stdio for AI Agent integration.

Protocol: Model Context Protocol (MCP) using JSON-RPC 2.0 over stdio.

Usage:
    python -m mcp_server                  # Start the MCP server
    python -m mcp_server --help           # Show help

Environment variables:
    PPT_AGENT_API_URL        — Base URL of the Agent API (default: http://127.0.0.1:8000)
    PPT_APP_TOKEN            — App token for authentication (default: empty)
    PPT_MCP_CONTRACT_CHECK   — Set to "0" to skip contract negotiation (default: "1")

The server:
1. Reads JSON-RPC requests from stdin (one per line)
2. Dispatches to the appropriate handler
3. Writes JSON-RPC responses to stdout (one per line)
4. Never accesses the database or business services directly
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from typing import Any, Optional

from agent_client.client import AgentClient
from agent_contract.versions import (
    AGENT_API_VERSION,
    get_contract_hash,
    is_version_compatible,
)
from mcp_server import resources, tools


# MCP protocol version
MCP_PROTOCOL_VERSION = "2024-11-05"

# Server info
SERVER_NAME = "ppt-studio-mcp"
SERVER_VERSION = "1.0.0"

# Short timeout (seconds) for the API meta call during contract negotiation.
_NEGOTIATE_TIMEOUT = 5


class ContractMismatchError(Exception):
    """Raised when the MCP server and API service contracts are incompatible."""


class MCPServer:
    """Lightweight MCP server processing JSON-RPC 2.0 over stdio."""

    def __init__(self, base_url: Optional[str] = None, app_token: Optional[str] = None) -> None:
        self.base_url = base_url or os.environ.get("PPT_AGENT_API_URL", "http://127.0.0.1:8000")
        self.app_token = app_token or os.environ.get("PPT_APP_TOKEN", "")
        self._client: Optional[AgentClient] = None
        self._initialized = False
        self._contract_state: dict[str, Any] = {"checked": False, "match": None}

    @property
    def client(self) -> AgentClient:
        """Lazy-init the AgentClient."""
        if self._client is None:
            self._client = AgentClient(base_url=self.base_url, app_token=self.app_token)
        return self._client

    # ---- Message processing ----

    def handle_request(self, request: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Process a single JSON-RPC request and return a response (or None for notifications)."""
        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        try:
            result = self._dispatch(method, params)
            if req_id is None:
                return None  # Notification — no response
            return {"jsonrpc": "2.0", "id": req_id, "result": result}
        except ContractMismatchError as e:
            if req_id is None:
                return None
            return self._error_response(req_id, -32000, str(e))
        except Exception as e:
            if req_id is None:
                return None
            return self._error_response(req_id, -32603, str(e))

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        """Route an MCP method to its handler."""
        if method == "initialize":
            return self._handle_initialize(params)
        elif method == "notifications/initialized":
            self._initialized = True
            return {}
        elif method == "ping":
            return {}
        elif method == "tools/list":
            return self._handle_tools_list()
        elif method == "tools/call":
            return self._handle_tools_call(params)
        elif method == "resources/list":
            return self._handle_resources_list()
        elif method == "resources/read":
            return self._handle_resources_read(params)
        elif method == "resources/templates/list":
            return {"resourceTemplates": resources.list_resource_templates()}
        else:
            raise ValueError(f"Unknown method: {method}")

    # ---- Method handlers ----

    def _negotiate_contract(self) -> dict[str, Any]:
        """Compare local contract with the running API service.

        Returns a dict with keys:
        - ``checked``: whether negotiation was performed (False if bypassed).
        - ``match``: True / False / None (None = bypassed).
        - ``detail``: human-readable explanation.
        - ``api_meta``: the raw ``/meta`` response from the API, or None.
        """
        local_hash = get_contract_hash()
        local_version = AGENT_API_VERSION

        check_enabled = os.environ.get("PPT_MCP_CONTRACT_CHECK", "1") != "0"
        if not check_enabled:
            return {
                "checked": False,
                "match": None,
                "detail": "Contract check disabled (PPT_MCP_CONTRACT_CHECK=0)",
                "api_meta": None,
            }

        try:
            api_meta = self.client.get_meta(timeout=_NEGOTIATE_TIMEOUT)
        except Exception as exc:
            return {
                "checked": True,
                "match": False,
                "detail": (
                    f"Cannot reach API service at {self.base_url} for contract "
                    f"negotiation: {exc}. Ensure the API service is running and "
                    f"PPT_AGENT_API_URL is correct."
                ),
                "api_meta": None,
            }

        api_hash = api_meta.get("contract_hash", "")
        api_version = api_meta.get("agent_api_version", "")

        if api_hash == local_hash:
            return {
                "checked": True,
                "match": True,
                "detail": None,
                "api_meta": api_meta,
            }

        # Hashes differ — use semantic version to classify the mismatch.
        compatible, compat_detail = is_version_compatible(local_version, api_version)
        if not compatible:
            return {
                "checked": True,
                "match": False,
                "detail": (
                    f"Contract mismatch: local hash {local_hash} ({local_version}) "
                    f"vs API hash {api_hash} ({api_version}). {compat_detail}. "
                    f"Restart the MCP server with the matching code version."
                ),
                "api_meta": api_meta,
            }

        # Compatible minor/patch difference — allow with warning.
        return {
            "checked": True,
            "match": True,
            "detail": compat_detail,
            "api_meta": api_meta,
        }

    def _handle_initialize(self, params: dict[str, Any]) -> dict[str, Any]:
        """Handle the MCP initialize handshake with contract negotiation."""
        negotiation = self._negotiate_contract()
        self._contract_state = negotiation

        local_hash = get_contract_hash()
        server_info: dict[str, Any] = {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "agentApiVersion": AGENT_API_VERSION,
            "contractHash": local_hash,
            "contractMatch": negotiation["match"],
        }
        if negotiation.get("api_meta"):
            api_meta = negotiation["api_meta"]
            server_info["apiContractHash"] = api_meta.get("contract_hash", "")
            server_info["apiAgentApiVersion"] = api_meta.get("agent_api_version", "")
        if negotiation.get("detail"):
            server_info["mismatchDetail"] = negotiation["detail"]

        if negotiation["match"] is False:
            raise ContractMismatchError(negotiation["detail"])

        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"subscribe": False, "listChanged": False},
                "prompts": {"listChanged": False},
            },
            "serverInfo": server_info,
        }

    def _handle_tools_list(self) -> dict[str, Any]:
        """List all registered MCP tools."""
        return {"tools": tools.get_all_tool_definitions()}

    def _handle_tools_call(self, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool call."""
        # Safety guard: refuse if the contract negotiation detected a mismatch.
        contract_state = getattr(self, "_contract_state", {})
        if contract_state.get("match") is False:
            return {
                "content": [{
                    "type": "text",
                    "text": (
                        f"Tool calls are blocked due to a contract mismatch: "
                        f"{contract_state.get('detail', 'unknown error')}. "
                        f"Restart the MCP server with the matching code version."
                    ),
                }],
                "isError": True,
            }

        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        try:
            handler = tools.get_tool_handler(tool_name)
        except ValueError:
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}],
                "isError": True,
            }

        try:
            content = handler(arguments, self.client)
            is_error = any(bool(item.pop("_agent_error", False)) for item in content if isinstance(item, dict))
            return {"content": content, "isError": is_error}
        except Exception as exc:
            return {
                "content": [{"type": "text", "text": f"Tool execution failed: {exc}"}],
                "isError": True,
            }

    def _handle_resources_list(self) -> dict[str, Any]:
        """List resource templates (static — actual resources are project-scoped)."""
        return {"resources": []}

    def _handle_resources_read(self, params: dict[str, Any]) -> dict[str, Any]:
        """Read a resource by URI."""
        uri = params.get("uri", "")
        return resources.read_resource(uri, self.client)

    # ---- Error handling ----

    def _error_response(self, req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }

    # ---- Main loop ----

    def run(self) -> None:
        """Main read-process-write loop."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                response = self._error_response(None, -32700, "Parse error")
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
                continue

            response = self.handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()


def run_server() -> None:
    """Entry point for running the MCP server from command line."""
    server = MCPServer()
    server.run()


if __name__ == "__main__":
    run_server()
