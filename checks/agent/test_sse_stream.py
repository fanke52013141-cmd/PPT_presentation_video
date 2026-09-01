"""Tests for SSE real-time pipeline progress streaming.

Covers:
- SSE event frame formatting (_sse_event, _sse_heartbeat)
- Generator behavior: initial event, deduplication, terminal close
- Capability registry entry
- SSE frame format compliance (event:, data:, double newline terminator)
"""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))


# ---------------------------------------------------------------------------
# SSE frame formatting helpers
# ---------------------------------------------------------------------------

def test_sse_event_format():
    """_sse_event must produce a valid SSE frame with event and data lines."""
    from agent_api.routes import _sse_event

    data = {"status": "running", "stage": "storyboard"}
    frame = _sse_event(data, event_name="progress")

    assert isinstance(frame, bytes)
    text = frame.decode("utf-8")
    assert text.startswith("event: progress\n")
    assert "data: " in text
    assert text.endswith("\n\n")

    # The data line must be valid JSON
    json_part = text.split("data: ", 1)[1].strip()
    parsed = json.loads(json_part)
    assert parsed["status"] == "running"
    assert parsed["stage"] == "storyboard"


def test_sse_event_custom_event_name():
    """_sse_event must accept arbitrary event names."""
    from agent_api.routes import _sse_event

    frame = _sse_event({"done": True}, event_name="complete")
    text = frame.decode("utf-8")
    assert text.startswith("event: complete\n")


def test_sse_heartbeat_format():
    """_sse_heartbeat must produce a comment-only SSE line."""
    from agent_api.routes import _sse_heartbeat

    hb = _sse_heartbeat()
    assert isinstance(hb, bytes)
    text = hb.decode("utf-8")
    assert text.startswith(": heartbeat")
    assert text.endswith("\n\n")


# ---------------------------------------------------------------------------
# Generator behavior
# ---------------------------------------------------------------------------

def _make_status(status: str = "idle", stage: str = "", run_id: str = "") -> dict:
    return {
        "status": status,
        "current_stage": stage,
        "run_id": run_id,
        "stages": [
            {"id": "preflight", "status": "done"},
            {"id": "storyboard", "status": "pending"},
        ],
        "blocking_errors": [],
        "review_checkpoint": "",
        "updated_at": "2026-01-01T00:00:00Z",
    }


def test_sse_generator_emits_initial_event_for_idle():
    """Generator must emit a progress event then a complete event for idle status."""
    from agent_api.routes import _sse_generator

    mock_project = MagicMock()
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = mock_project

    mock_factory = MagicMock(return_value=mock_session)

    status_sequence = [_make_status(status="idle", stage="")]

    with patch("one_click_orchestrator.get_one_click_status", side_effect=status_sequence):
        gen = _sse_generator("test-proj", mock_factory, poll_interval=0.01, max_duration=5)
        frames = list(gen)

    # Should have at least a progress frame and a complete frame
    decoded = [f.decode("utf-8") for f in frames]
    has_progress = any("event: progress" in d for d in decoded)
    has_complete = any("event: complete" in d for d in decoded)
    assert has_progress, f"Missing progress event in {decoded}"
    assert has_complete, f"Missing complete event in {decoded}"


def test_sse_generator_emits_terminal_for_completed():
    """Generator must close with a complete event when pipeline finishes."""
    from agent_api.routes import _sse_generator

    mock_project = MagicMock()
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = mock_project
    mock_factory = MagicMock(return_value=mock_session)

    completed_status = _make_status(status="completed", stage="output", run_id="run-123")

    with patch("one_click_orchestrator.get_one_click_status", return_value=completed_status):
        gen = _sse_generator("test-proj", mock_factory, poll_interval=0.01, max_duration=5)
        frames = list(gen)

    decoded = [f.decode("utf-8") for f in frames]
    # Should have progress then complete for a terminal state
    progress_frames = [d for d in decoded if "event: progress" in d]
    complete_frames = [d for d in decoded if "event: complete" in d]
    assert len(progress_frames) >= 1
    assert len(complete_frames) == 1

    # Verify the complete frame data
    complete_json = complete_frames[0].split("data: ", 1)[1].strip()
    parsed = json.loads(complete_json)
    assert parsed["status"] == "completed"
    assert parsed["current_stage"] == "output"


def test_sse_generator_emits_error_for_missing_project():
    """Generator must emit an error event when project is not found."""
    from agent_api.routes import _sse_generator

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None
    mock_factory = MagicMock(return_value=mock_session)

    gen = _sse_generator("ghost-proj", mock_factory, poll_interval=0.01, max_duration=5)
    frames = list(gen)

    decoded = [f.decode("utf-8") for f in frames]
    error_frames = [d for d in decoded if "event: error" in d]
    assert len(error_frames) == 1
    assert "Project not found" in error_frames[0]


def test_sse_generator_dedup_consecutive_same_state():
    """Generator must deduplicate events when status hasn't changed."""
    from agent_api.routes import _sse_generator

    mock_project = MagicMock()
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = mock_project
    mock_factory = MagicMock(return_value=mock_session)

    running_status = _make_status(status="running", stage="storyboard", run_id="run-1")

    with patch("one_click_orchestrator.get_one_click_status", return_value=running_status):
        gen = _sse_generator("test-proj", mock_factory, poll_interval=0.01, max_duration=0.1)
        frames = list(gen)

    decoded = [f.decode("utf-8") for f in frames]
    # With max_duration very short and same status, we should see at most:
    # 1 initial progress event + heartbeat(s) + close event (timeout)
    progress_frames = [d for d in decoded if "event: progress" in d]
    # Only the first call should produce a progress event (dedup)
    assert len(progress_frames) == 1


# ---------------------------------------------------------------------------
# Capability registry
# ---------------------------------------------------------------------------

def test_sse_capability_registered():
    """The pipeline.stream capability must exist in the registry."""
    from agent_contract.capabilities import CAPABILITIES

    cap = next((c for c in CAPABILITIES if c.id == "pipeline.stream"), None)
    assert cap is not None
    assert cap.agent_api_method == "GET"
    assert cap.agent_api_path == "/api/agent/v1/projects/{project_id}/runs/latest/stream"
    assert cap.mcp_tool_name == "ppt_pipeline_stream"
    assert cap.status.value == "stable"


def test_sse_terminal_states_contains_expected():
    """Terminal states must include the core terminal pipeline statuses."""
    from agent_api.routes import _SSE_TERMINAL_STATES

    for expected in ("completed", "failed", "idle", "paused", "waiting_for_review"):
        assert expected in _SSE_TERMINAL_STATES, f"Missing terminal state: {expected}"
