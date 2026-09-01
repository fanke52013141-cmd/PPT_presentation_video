"""MCP Tools — auto-registered from the capability registry.

Each tool is defined by its AgentCapability entry. The input schema is
generated from the Pydantic request model. The handler delegates to
AgentClient, which calls the Agent API.

This module does NOT hand-write tool definitions. Everything is derived
from agent_contract.capabilities.CAPABILITIES.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from agent_client.client import AgentClient, AgentClientError
from agent_contract.capabilities import (
    CAPABILITIES,
    CapabilityStatus,
    AgentCapability,
)
from agent_contract.schema import capability_input_schema
from mcp_server import presenters


# ---------------------------------------------------------------------------
# Tool handler factory
# ---------------------------------------------------------------------------

def _make_tool_handler(cap: AgentCapability) -> Callable:
    """Create a handler function for a capability.

    Each handler receives (arguments: dict, client: AgentClient) and returns
    a list of MCP content blocks.
    """
    cap_id = cap.id

    def handler(arguments: dict[str, Any], client: AgentClient) -> list[dict[str, Any]]:
        try:
            result = _dispatch(cap_id, arguments, client)
            return _format_result(cap_id, result)
        except AgentClientError as exc:
            # Retain a human-readable content block for direct callers, while
            # marking it for MCPServer to return the protocol-level isError.
            return [{
                "type": "text",
                "text": f"API Error ({exc.status_code}): {exc}",
                "_agent_error": True,
            }]
        except Exception as exc:
            return [{
                "type": "text",
                "text": f"Tool execution failed: {exc}",
                "_agent_error": True,
            }]

    handler.__name__ = f"handle_{cap_id.replace('.', '_')}"
    handler.__doc__ = cap.description
    return handler


def _dispatch(cap_id: str, args: dict[str, Any], client: AgentClient) -> dict[str, Any]:
    """Route a capability ID to the appropriate AgentClient method."""

    if cap_id == "project.create":
        return client.create_project(
            name=args.get("name", ""),
            description=args.get("description", ""),
            canvas_profile=args.get("canvas_profile", "landscape_16_9"),
            automation_mode=args.get("automation_mode", "auto"),
            review_policy=args.get("review_policy", "none"),
            idempotency_key=args.get("idempotency_key"),
        )

    elif cap_id == "project.list":
        return client.list_projects(
            status=args.get("status"),
            limit=args.get("limit", 50),
        )

    elif cap_id == "project.get":
        pid = args.get("project_id", "")
        return client.get_project(pid)

    elif cap_id == "project.update":
        pid = args.get("project_id", "")
        return client.update_project(
            project_id=pid,
            name=args.get("name"),
            description=args.get("description"),
            ai_mode=args.get("ai_mode"),
            expected_revision=args.get("expected_revision"),
            idempotency_key=args.get("idempotency_key"),
        )

    elif cap_id == "source.set":
        pid = args.get("project_id", "")
        return client.set_source(
            project_id=pid,
            content=args.get("content"),
            topic=args.get("topic"),
            idempotency_key=args.get("idempotency_key"),
        )

    elif cap_id == "pipeline.run":
        pid = args.get("project_id", "")
        return client.start_pipeline(
            project_id=pid,
            start_from=args.get("start_from"),
            stop_at=args.get("stop_at"),
            mode=args.get("mode", "resume"),
            idempotency_key=args.get("idempotency_key"),
        )

    elif cap_id == "pipeline.status":
        pid = args.get("project_id", "")
        return client.get_pipeline_status(pid)

    elif cap_id == "pipeline.resume":
        pid = args.get("project_id", "")
        return client.resume_pipeline(
            project_id=pid,
            stop_at=args.get("stop_at"),
            idempotency_key=args.get("idempotency_key"),
        )

    elif cap_id == "checkpoint.approve":
        pid = args.get("project_id", "")
        cp = args.get("checkpoint", "")
        return client.approve_checkpoint(
            project_id=pid,
            checkpoint=cp,
            approved=args.get("approved", True),
            notes=args.get("notes", ""),
            idempotency_key=args.get("idempotency_key"),
        )

    elif cap_id == "stage.get":
        pid = args.get("project_id", "")
        stage = args.get("stage", "storyboard")
        return client.get_stage(pid, stage)

    elif cap_id == "image.regenerate":
        pid = args.get("project_id", "")
        sid = args.get("slide_id", "")
        return client.regenerate_image(
            project_id=pid,
            slide_id=sid,
            instruction=args.get("instruction", ""),
            idempotency_key=args.get("idempotency_key"),
        )

    elif cap_id == "narration.update":
        pid = args.get("project_id", "")
        sid = args.get("slide_id", "")
        return client.update_narration(
            project_id=pid,
            slide_id=sid,
            narration_text=args.get("narration_text", ""),
            expected_revision=args.get("expected_revision"),
            idempotency_key=args.get("idempotency_key"),
        )

    elif cap_id == "tts.synthesize":
        pid = args.get("project_id", "")
        return client.synthesize_tts(
            project_id=pid,
            slide_ids=args.get("slide_ids"),
            idempotency_key=args.get("idempotency_key"),
        )

    elif cap_id == "video.render":
        pid = args.get("project_id", "")
        return client.render_video(pid, idempotency_key=args.get("idempotency_key"))

    elif cap_id == "artifacts.list":
        pid = args.get("project_id", "")
        return client.list_artifacts(
            project_id=pid,
            artifact_type=args.get("artifact_type"),
            slide_id=args.get("slide_id"),
        )

    elif cap_id == "artifact.get":
        pid = args.get("project_id", "")
        aid = args.get("artifact_id", "")
        return client.get_artifact(pid, aid)

    elif cap_id == "diagnostics":
        return client.get_diagnostics()

    elif cap_id == "digital_human.config.get":
        pid = args.get("project_id", "")
        return client.get_digital_human_config(pid)

    elif cap_id == "digital_human.config.update":
        pid = args.get("project_id", "")
        config = args.get("config", {})
        return client.update_digital_human_config(pid, config)

    elif cap_id == "digital_human.health":
        pid = args.get("project_id", "")
        return client.check_digital_human_health(pid)

    elif cap_id == "digital_human.generate":
        pid = args.get("project_id", "")
        return client.generate_digital_human(pid)

    raise ValueError(f"Unknown capability for dispatch: {cap_id}")


def _format_result(cap_id: str, result: dict[str, Any]) -> list[dict[str, Any]]:
    """Format an API response into MCP content blocks."""
    blocks: list[dict[str, Any]] = []

    if cap_id == "project.create":
        proj = result.get("project", result)
        blocks.append(presenters.present_project_summary(proj))

    elif cap_id == "project.list":
        projects = result.get("projects", [])
        for p in projects:
            blocks.append(presenters.present_project_summary(p))

    elif cap_id.startswith("pipeline."):
        blocks.append(presenters.present_operation_status(result))

    elif cap_id == "checkpoint.approve":
        blocks.append({"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False, default=str)})

    elif cap_id == "artifacts.list":
        artifacts = result.get("artifacts", [])
        proj_id = result.get("project_id", "")
        blocks.append(presenters.present_artifact_list_as_text(proj_id, artifacts))

    elif cap_id == "artifact.get":
        blocks.append(presenters.present_artifact_as_text(result))

    elif cap_id == "diagnostics":
        blocks.append({"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False, default=str)})

    else:
        # Default: return JSON text
        blocks.append({"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False, default=str)})

    return blocks


# ---------------------------------------------------------------------------
# Tool registry (auto-generated)
# ---------------------------------------------------------------------------

def get_all_tool_definitions() -> list[dict[str, Any]]:
    """Return MCP tool definitions for all stable capabilities.

    Each definition contains: name, description, inputSchema.
    The inputSchema is derived from the capability's Pydantic model.
    """
    definitions: list[dict[str, Any]] = []
    for cap in CAPABILITIES:
        if cap.status == CapabilityStatus.removed:
            continue
        schema = capability_input_schema(cap)
        definitions.append({
            "name": cap.mcp_tool_name,
            "description": _build_description(cap),
            "inputSchema": schema,
        })
    return definitions


def _build_description(cap: AgentCapability) -> str:
    """Build a human-readable description with status and usage hints."""
    parts = [cap.description]
    if cap.status == CapabilityStatus.deprecated and cap.replaced_by:
        parts.append(f"[DEPRECATED — use {cap.replaced_by}]")
    elif cap.status == CapabilityStatus.experimental:
        parts.append("[EXPERIMENTAL]")
    if cap.long_running:
        parts.append("This is a long-running operation — returns an operation_id for polling.")
    if cap.destructive:
        parts.append("⚠ Destructive operation — confirm before executing.")
    return " ".join(parts)


def get_tool_handler(tool_name: str) -> Callable:
    """Get the handler function for a specific MCP tool name."""
    for cap in CAPABILITIES:
        if cap.mcp_tool_name == tool_name and cap.status != CapabilityStatus.removed:
            return _make_tool_handler(cap)
    raise ValueError(f"Unknown MCP tool: {tool_name}")


def get_tool_names() -> list[str]:
    """Return all registered tool names (excluding removed)."""
    return [
        cap.mcp_tool_name
        for cap in CAPABILITIES
        if cap.status != CapabilityStatus.removed
    ]
