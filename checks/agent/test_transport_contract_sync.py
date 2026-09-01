"""Prevent drift between the Agent contract, API routes, MCP and CLI."""

from __future__ import annotations

from agent_contract.capabilities import CAPABILITIES, CapabilityStatus


def test_every_capability_has_a_matching_agent_api_route():
    from agent_api.routes import router

    routes = {
        (method, route.path)
        for route in router.routes
        for method in route.methods or set()
        if method not in {"HEAD", "OPTIONS"}
    }
    for cap in CAPABILITIES:
        if cap.status != CapabilityStatus.removed:
            assert (cap.agent_api_method, cap.agent_api_path) in routes, cap.id


def test_meta_exposes_complete_machine_readable_capabilities():
    from agent_contract.versions import get_meta

    details = {item["id"]: item for item in get_meta()["capability_details"]}
    for cap in CAPABILITIES:
        if cap.status == CapabilityStatus.removed:
            continue
        detail = details[cap.id]
        assert detail["mcp_tool"] == cap.mcp_tool_name
        assert detail["cli_command"] == cap.cli_command
        assert "input_schema" in detail and "output_schema" in detail
