"""MCP Server package — exposes PPT Studio capabilities to AI Agents.

Architecture:
    MCP Tools (from capability registry)
        → AgentClient (HTTP)
            → Agent API (/api/agent/v1/*)
                → Existing Pipeline Services

The MCP server never accesses the database, filesystem, or business services
directly. All operations go through AgentClient → Agent API.
"""

from mcp_server.server import MCPServer, run_server

__all__ = ["MCPServer", "run_server"]
