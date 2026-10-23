"""Prevent drift between the Agent contract, API routes, MCP and CLI."""

from __future__ import annotations

from agent_contract.capabilities import CAPABILITIES, CapabilityStatus


def test_every_capability_has_a_matching_agent_api_route():
    from agent_api.routes import router

    from route_inventory import iter_effective_routes
    routes = {
        (method, route.path)
        for route in iter_effective_routes(router)
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
        assert detail["mcp_enabled"] is cap.mcp_enabled
        assert detail["cli_command"] == cap.cli_command
        assert "input_schema" in detail and "output_schema" in detail


def test_every_agent_route_is_a_registered_capability():
    """反向断言：Agent 路由要么登记为能力，要么出现在显式豁免清单中。

    历史缺陷：仅有的 capabilities→routes 单向断言放过了 6 条未登记的
    业务路由（DELETE 项目、checkpoints 列表、slide 图片/音频、最新视频、
    artifact 内容下载），它们因此缺席 OpenAPI 与 capability-matrix。
    """
    from agent_api.routes import router

    # 显式豁免：传输/文档端点，不是对外承诺的业务能力。
    from agent_contract.discovery import BOOTSTRAP_PATHS
    excluded = {("POST" if path.endswith("/invoke") else "GET", path) for path in BOOTSTRAP_PATHS}
    registered = {
        (cap.agent_api_method, cap.agent_api_path)
        for cap in CAPABILITIES
        if cap.status != CapabilityStatus.removed
    }
    missing = []
    from route_inventory import iter_effective_routes
    for route in iter_effective_routes(router):
        path = getattr(route, "path", "")
        if not path.startswith("/api/agent/v1"):
            continue
        for method in getattr(route, "methods", None) or set():
            if method in {"HEAD", "OPTIONS"}:
                continue
            if (method, path) not in registered and (method, path) not in excluded:
                missing.append((method, path))
    assert missing == [], (
        "Agent routes missing from the capability registry "
        f"(register them or extend the exclusion list with a reason): {missing}"
    )
