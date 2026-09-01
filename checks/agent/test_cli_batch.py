"""Tests for CLI batch operation commands.

Covers:
- Parser construction for batch subcommands
- cmd_batch_status behavior with mock client
- cmd_batch_render behavior with mock client
- cmd_batch_cleanup behavior with mock client
- CLI_COMMANDS registry contains batch commands
- Client delete_project method existence
"""

from __future__ import annotations

import json
import os
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------

def test_batch_parser_exists():
    """The parser must include a 'batch' subcommand."""
    from cli.pptctl import build_parser

    parser = build_parser()
    # Verify the parser accepts 'batch' as a command
    args = parser.parse_args(["batch", "status"])
    assert args.command == "batch"
    assert args.batch_action == "status"


def test_batch_parser_status_has_func():
    """batch status must have a callable func."""
    from cli.pptctl import build_parser

    parser = build_parser()
    args = parser.parse_args(["batch", "status"])
    assert hasattr(args, "func")
    assert callable(args.func)


def test_batch_parser_render_has_speed():
    """batch render must accept --speed."""
    from cli.pptctl import build_parser

    parser = build_parser()
    args = parser.parse_args(["batch", "render", "--speed", "1.5"])
    assert args.speed == "1.5"


def test_batch_parser_cleanup_has_status():
    """batch cleanup must accept --status."""
    from cli.pptctl import build_parser

    parser = build_parser()
    args = parser.parse_args(["batch", "cleanup", "--status", "completed"])
    assert args.status == "completed"


# ---------------------------------------------------------------------------
# CLI_COMMANDS registry
# ---------------------------------------------------------------------------

def test_cli_commands_includes_batch():
    """CLI_COMMANDS must contain all batch operations."""
    from cli.pptctl import CLI_COMMANDS

    assert "batch status" in CLI_COMMANDS
    assert "batch render" in CLI_COMMANDS
    assert "batch cleanup" in CLI_COMMANDS


# ---------------------------------------------------------------------------
# Client delete method
# ---------------------------------------------------------------------------

def test_client_has_delete_project():
    """AgentClient must have a delete_project method."""
    from agent_client.client import AgentClient

    assert hasattr(AgentClient, "delete_project")
    assert callable(getattr(AgentClient, "delete_project"))


# ---------------------------------------------------------------------------
# Command execution with mock client
# ---------------------------------------------------------------------------

def test_cmd_batch_status_executes():
    """cmd_batch_status must iterate projects and collect statuses."""
    from cli.pptctl import cmd_batch_status
    from argparse import Namespace

    mock_client = MagicMock()
    mock_client.list_projects.return_value = {
        "projects": [
            {"project_id": "proj-1"},
            {"project_id": "proj-2"},
        ]
    }
    mock_client.get_pipeline_status.side_effect = [
        {"status": "running", "current_stage": "storyboard"},
        {"status": "completed", "current_stage": "output"},
    ]

    with patch("cli.pptctl.AgentClient", return_value=mock_client):
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            cmd_batch_status(Namespace(
                base_url="http://localhost:8000",
                token="",
                status=None,
            ))

    output = json.loads(mock_stdout.getvalue())
    assert output["total"] == 2
    assert len(output["results"]) == 2
    assert output["results"][0]["project_id"] == "proj-1"
    assert len(output["errors"]) == 0


def test_cmd_batch_status_handles_errors():
    """cmd_batch_status must collect errors per project."""
    from cli.pptctl import cmd_batch_status
    from cli.pptctl import AgentClientError
    from argparse import Namespace

    mock_client = MagicMock()
    mock_client.list_projects.return_value = {
        "projects": [{"project_id": "ok-proj"}, {"project_id": "err-proj"}]
    }

    def mock_status(pid):
        if pid == "err-proj":
            raise AgentClientError("Connection failed")
        return {"status": "idle"}

    mock_client.get_pipeline_status.side_effect = mock_status

    with patch("cli.pptctl.AgentClient", return_value=mock_client):
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            cmd_batch_status(Namespace(
                base_url="http://localhost:8000",
                token="",
                status=None,
            ))

    output = json.loads(mock_stdout.getvalue())
    assert output["total"] == 1
    assert len(output["results"]) == 1
    assert len(output["errors"]) == 1
    assert output["errors"][0]["project_id"] == "err-proj"


def test_cmd_batch_render_executes():
    """cmd_batch_render must submit render jobs for all projects."""
    from cli.pptctl import cmd_batch_render
    from argparse import Namespace

    mock_client = MagicMock()
    mock_client.list_projects.return_value = {
        "projects": [{"project_id": "proj-1"}, {"project_id": "proj-2"}]
    }
    mock_client.render_video.side_effect = [
        {"operation_id": "render-1"},
        {"operation_id": "render-2"},
    ]

    with patch("cli.pptctl.AgentClient", return_value=mock_client):
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            cmd_batch_render(Namespace(
                base_url="http://localhost:8000",
                token="",
                speed="1.0",
            ))

    output = json.loads(mock_stdout.getvalue())
    assert output["total"] == 2
    assert len(output["results"]) == 2


def test_cmd_batch_cleanup_executes():
    """cmd_batch_cleanup must delete projects."""
    from cli.pptctl import cmd_batch_cleanup
    from argparse import Namespace

    mock_client = MagicMock()
    mock_client.list_projects.return_value = {
        "projects": [{"project_id": "old-1"}, {"project_id": "old-2"}]
    }
    mock_client.delete_project.return_value = {"deleted": True}

    with patch("cli.pptctl.AgentClient", return_value=mock_client):
        with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
            cmd_batch_cleanup(Namespace(
                base_url="http://localhost:8000",
                token="",
                status="completed",
            ))

    output = json.loads(mock_stdout.getvalue())
    assert output["total"] == 2
    assert len(output["deleted"]) == 2
    assert mock_client.delete_project.call_count == 2
