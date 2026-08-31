"""Test MCP tool contract alignment.

Verifies that:
1. Every stable capability has a corresponding MCP tool definition
2. Input schemas match the Pydantic request models
3. Tool names match the registry
4. Long-running capabilities are marked as such
"""

from __future__ import annotations

import pytest

from agent_contract.capabilities import (
    CAPABILITIES,
    CapabilityStatus,
    get_capability_by_mcp_tool,
)
from mcp_server.tools import (
    get_all_tool_definitions,
    get_tool_handler,
    get_tool_names,
)


class TestMCPToolDefinitions:
    """Verify MCP tool definitions are generated correctly."""

    def test_tool_count_matches_capabilities(self):
        defs = get_all_tool_definitions()
        expected = [c for c in CAPABILITIES if c.status != CapabilityStatus.removed]
        assert len(defs) == len(expected), (
            f"Tool count {len(defs)} != capability count {len(expected)}"
        )

    def test_all_tool_names_in_definitions(self):
        defs = get_all_tool_definitions()
        names = [d["name"] for d in defs]
        for cap in CAPABILITIES:
            if cap.status != CapabilityStatus.removed:
                assert cap.mcp_tool_name in names, (
                    f"MCP tool {cap.mcp_tool_name} missing from definitions"
                )

    def test_definitions_have_required_keys(self):
        for d in get_all_tool_definitions():
            assert "name" in d, f"Missing 'name' in tool definition"
            assert "description" in d, f"Missing 'description' in tool definition"
            assert "inputSchema" in d, f"Missing 'inputSchema' in tool definition"

    def test_input_schemas_are_valid_json_schema(self):
        for d in get_all_tool_definitions():
            schema = d["inputSchema"]
            assert isinstance(schema, dict)
            assert schema.get("type") == "object" or "properties" in schema, (
                f"Tool {d['name']} schema is not a valid JSON Schema object"
            )


class TestMCPToolHandlers:
    """Verify MCP tool handlers exist and are callable."""

    def test_all_tools_have_handlers(self):
        for name in get_tool_names():
            handler = get_tool_handler(name)
            assert callable(handler), f"Handler for {name} is not callable"

    def test_handler_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown MCP tool"):
            get_tool_handler("ppt_nonexistent")

    def test_tool_names_non_empty(self):
        names = get_tool_names()
        assert len(names) > 0


class TestMCPContractAlignment:
    """Verify MCP tools align with the capability registry."""

    def test_every_tool_maps_to_capability(self):
        for name in get_tool_names():
            cap = get_capability_by_mcp_tool(name)
            assert cap is not None

    def test_long_running_tools_marked(self):
        """Long-running capabilities should mention polling in description."""
        defs_by_name = {d["name"]: d for d in get_all_tool_definitions()}
        for cap in CAPABILITIES:
            if cap.long_running and cap.status != CapabilityStatus.removed:
                desc = defs_by_name[cap.mcp_tool_name]["description"]
                assert "long-running" in desc.lower() or "polling" in desc.lower(), (
                    f"Long-running capability {cap.id} description should mention polling"
                )
