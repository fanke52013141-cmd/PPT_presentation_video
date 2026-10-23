"""Current capability descriptions shared by discovery and execution."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, create_model

from agent_contract.capabilities import AgentCapability
from agent_contract.models import GenerationKind
from agent_contract.schema import capability_input_schema, capability_output_schema


BOOTSTRAP_PATHS = frozenset({
    "/api/agent/v1/meta", "/api/agent/v1/openapi.json", "/api/agent/v1/docs",
    "/api/agent/v1/capabilities", "/api/agent/v1/capabilities/{capability_id}",
    "/api/agent/v1/invoke",
})


def path_names(cap: AgentCapability) -> list[str]:
    return re.findall(r"\{([a-zA-Z_][a-zA-Z_0-9]*)\}", cap.agent_api_path)


def required_scope(cap: AgentCapability) -> str:
    if "/runs" in cap.agent_api_path or cap.agent_api_path.endswith("/render"):
        return "pipeline:write"
    if "/artifacts" in cap.agent_api_path and cap.agent_api_method == "GET":
        return "artifact:read"
    return "project:read" if cap.agent_api_method == "GET" else "project:write"


def response_kind(cap: AgentCapability) -> str:
    if cap.transport != "json":
        return cap.transport
    if cap.id == "pipeline.stream":
        return "event_stream"
    if cap.id in {"image.get", "audio.get", "video.latest", "artifact.download"}:
        return "binary"
    return "json"


def input_model(cap: AgentCapability) -> type[BaseModel]:
    """Validate full arguments, including path fields, without discarding typos."""
    fields: dict[str, Any] = {}
    for name in path_names(cap):
        field_type = GenerationKind if name == "stage" and cap.id.startswith("generation.") else str
        fields[name] = (field_type, ...)
    return create_model(
        cap.id.replace(".", "_") + "Arguments",
        __base__=cap.request_model,
        __config__=ConfigDict(extra="forbid"),
        **fields,
    )


def describe_capability(cap: AgentCapability) -> dict[str, Any]:
    names = path_names(cap)
    schema = capability_input_schema(cap)
    fields = schema.get("properties", {})
    location = "query" if cap.agent_api_method in {"GET", "DELETE"} else "body"
    data = {
        "id": cap.id, "version": cap.version, "behavior_version": cap.behavior_version,
        "status": cap.status.value, "domain": cap.id.split(".")[0],
        "description": cap.description, "method": cap.agent_api_method,
        "path": cap.agent_api_path, "mcp_tool": cap.mcp_tool_name,
        "mcp_enabled": cap.mcp_enabled, "cli_command": cap.cli_command,
        "input_schema": schema, "output_schema": capability_output_schema(cap),
        "bindings": {name: "path" if name in names else location for name in fields},
        "required_scopes": [required_scope(cap)],
        "response_kind": response_kind(cap), "invocable": response_kind(cap) == "json",
        "long_running": cap.long_running, "destructive": cap.destructive,
        "idempotency": {
            "supported": "idempotency_key" in fields,
            "key_required": False,
            **({"replay_retention_days": 7, "expired_key": "reject", "uncertain_outcome": "inspect_before_retry"}
               if "idempotency_key" in fields else {}),
        },
        "concurrency": {"expected_revision_supported": "expected_revision" in fields,
                        "resource_scope": "project" if "expected_revision" in fields else None},
    }
    encoded = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    data["contract_revision"] = hashlib.sha256(encoded.encode()).hexdigest()[:24]
    return data
