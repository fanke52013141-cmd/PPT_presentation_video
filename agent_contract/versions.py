"""Version and compatibility management for the Agent contract.

Provides:
- AGENT_API_VERSION: semantic version of the Agent API
- CONTRACT_VERSION: hash fingerprint of the current capability registry
- get_meta(): the /api/agent/v1/meta response
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from agent_contract.capabilities import CAPABILITIES, CapabilityStatus


AGENT_API_VERSION = "1.0.0"


def get_contract_hash() -> str:
    """Compute a deterministic hash of the current capability registry.

    This hash changes when capabilities are added, removed, or their
    request/response models change. MCP servers use it to verify compatibility.
    """
    # Build a deterministic representation of the registry
    parts: list[str] = []
    for cap in sorted(CAPABILITIES, key=lambda c: c.id):
        # Bare BaseModel raises AttributeError; only subclasses can generate schemas
        try:
            req_schema = cap.request_model.model_json_schema() if cap.request_model is not BaseModel else {}
        except Exception:
            req_schema = {}
        try:
            res_schema = cap.response_model.model_json_schema() if cap.response_model is not BaseModel else {}
        except Exception:
            res_schema = {}
        entry = {
            "id": cap.id,
            "version": cap.version,
            "status": cap.status.value,
            "method": cap.agent_api_method,
            "path": cap.agent_api_path,
            "mcp_tool": cap.mcp_tool_name,
            "cli": cap.cli_command,
            "request_schema": req_schema,
            "response_schema": res_schema,
        }
        parts.append(json.dumps(entry, sort_keys=True, ensure_ascii=False))
    combined = "\n".join(parts)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()[:16]


CONTRACT_VERSION = get_contract_hash()


def get_capability_versions() -> list[str]:
    """Return capability identifiers with versions, e.g. ['project.create@1.0', ...]."""
    return [f"{c.id}@{c.version}" for c in CAPABILITIES if c.status != CapabilityStatus.removed]


def get_meta() -> dict[str, Any]:
    """Build the /api/agent/v1/meta response."""
    try:
        # Read application version if available
        import importlib.metadata
        app_version = importlib.metadata.version("ppt-studio")
    except Exception:
        app_version = "dev"

    return {
        "agent_api_version": AGENT_API_VERSION,
        "contract_hash": CONTRACT_VERSION,
        "application_version": app_version,
        "capabilities": get_capability_versions(),
    }
