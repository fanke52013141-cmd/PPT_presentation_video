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

from agent_contract.capabilities import CAPABILITIES, CapabilityStatus
from agent_contract.schema import capability_input_schema, capability_output_schema


AGENT_API_VERSION = "1.3.0"


def get_contract_hash() -> str:
    """Compute a deterministic hash of the current capability registry.

    This hash changes when capabilities are added, removed, or their
    request/response models change. MCP servers use it to verify compatibility.
    """
    # Build a deterministic representation of the registry
    parts: list[str] = []
    for cap in sorted(CAPABILITIES, key=lambda c: c.id):
        req_schema = capability_input_schema(cap)
        res_schema = capability_output_schema(cap)
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


def is_version_compatible(local: str, remote: str) -> tuple[bool, str]:
    """Check semantic version compatibility between two ``X.Y.Z`` strings.

    Returns ``(compatible, detail)``:
    - Major version difference → ``(False, explanation)``.
    - Minor/patch difference → ``(True, warning_text)``.
    - Identical → ``(True, "")``.
    """
    def _parse(ver: str) -> tuple[int, int, int]:
        parts = ver.split(".")
        return (
            int(parts[0]) if len(parts) > 0 and parts[0].lstrip("-").isdigit() else 0,
            int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0,
            int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0,
        )

    try:
        local_major, local_minor, local_patch = _parse(local)
        remote_major, remote_minor, remote_patch = _parse(remote)
    except (ValueError, IndexError):
        return False, f"Cannot parse version: local={local!r}, remote={remote!r}"

    if local_major != remote_major:
        return (
            False,
            f"Major version mismatch: local {local} vs remote {remote}",
        )

    if local_minor != remote_minor or local_patch != remote_patch:
        return True, f"Minor/patch difference: local {local} vs remote {remote}"

    return True, ""


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
        "capability_details": [
            {
                "id": cap.id,
                "version": cap.version,
                "status": cap.status.value,
                "description": cap.description,
                "method": cap.agent_api_method,
                "path": cap.agent_api_path,
                "mcp_tool": cap.mcp_tool_name,
                "cli_command": cap.cli_command,
                "input_schema": capability_input_schema(cap),
                "output_schema": capability_output_schema(cap),
            }
            for cap in CAPABILITIES
            if cap.status != CapabilityStatus.removed
        ],
    }
