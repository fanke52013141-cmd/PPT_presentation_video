"""Tests for digital-human Agent API capability exposure."""

from __future__ import annotations

import json
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from agent_client.client import AgentClient


# ------------------------------------------------------------------
# Client method existence
# ------------------------------------------------------------------

def test_client_has_digital_human_methods():
    """All four digital-human client methods exist."""
    assert hasattr(AgentClient, "get_digital_human_config")
    assert hasattr(AgentClient, "check_digital_human_health")
    assert hasattr(AgentClient, "generate_digital_human")
    assert hasattr(AgentClient, "update_digital_human_config")


# ------------------------------------------------------------------
# Capability registry
# ------------------------------------------------------------------

def test_digital_human_capabilities_registered():
    """All four digital-human capabilities appear in the registry."""
    from agent_contract.capabilities import CAPABILITIES
    ids = {cap.id for cap in CAPABILITIES}
    assert "digital_human.config.get" in ids
    assert "digital_human.config.update" in ids
    assert "digital_human.health" in ids
    assert "digital_human.generate" in ids


def test_digital_human_capabilities_have_mcp_tools():
    """Each digital-human capability has an MCP tool name."""
    from agent_contract.capabilities import CAPABILITIES
    dh_caps = [c for c in CAPABILITIES if c.id.startswith("digital_human.")]
    assert len(dh_caps) == 4
    for cap in dh_caps:
        assert cap.mcp_tool_name.startswith("ppt_digital_human")


def test_digital_human_capabilities_are_stable():
    from agent_contract.capabilities import CAPABILITIES, CapabilityStatus
    dh_caps = [c for c in CAPABILITIES if c.id.startswith("digital_human.")]
    for cap in dh_caps:
        assert cap.status == CapabilityStatus.stable


# ------------------------------------------------------------------
# CLI command registration
# ------------------------------------------------------------------

def test_cli_digital_human_help():
    """CLI should have digital-human subcommands."""
    import subprocess
    import sys
    result = subprocess.run(
        [sys.executable, "-m", "cli.pptctl", "digital-human", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert "config" in result.stdout
    assert "health" in result.stdout
    assert "generate" in result.stdout


# ------------------------------------------------------------------
# MCP tool dispatch
# ------------------------------------------------------------------

def test_mcp_dispatch_digital_human_health():
    """MCP tools dispatch should route to client.check_digital_human_health."""
    from mcp_server.tools import _dispatch
    mock_client = MagicMock()
    mock_client.check_digital_human_health.return_value = {"available": True}
    result = _dispatch("digital_human.health", {"project_id": "test-proj"}, mock_client)
    mock_client.check_digital_human_health.assert_called_once_with("test-proj")
    assert result["available"] is True


def test_mcp_dispatch_digital_human_config_get():
    from mcp_server.tools import _dispatch
    mock_client = MagicMock()
    mock_client.get_digital_human_config.return_value = {"enabled": False}
    result = _dispatch("digital_human.config.get", {"project_id": "p1"}, mock_client)
    assert result["enabled"] is False


def test_mcp_dispatch_digital_human_generate():
    from mcp_server.tools import _dispatch
    mock_client = MagicMock()
    mock_client.generate_digital_human.return_value = {"success": True}
    result = _dispatch("digital_human.generate", {"project_id": "p1"}, mock_client)
    assert result["success"] is True
