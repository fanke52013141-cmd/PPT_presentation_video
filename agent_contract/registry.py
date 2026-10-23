"""Capability declaration primitives shared by domain modules.

``agent_contract/capabilities.py`` stays the aggregate registry; domain
modules declare their own ``CAPABILITIES`` lists with these dataclasses and
the aggregate imports them. Splitting the dataclass out avoids a circular
import between the aggregate and the domain declarations.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Type

from pydantic import BaseModel


class CapabilityStatus(str, Enum):
    experimental = "experimental"
    stable = "stable"
    deprecated = "deprecated"
    removed = "removed"


@dataclass(frozen=True)
class AgentCapability:
    """Describes a single Agent-facing capability and its mappings."""

    id: str
    version: str
    status: CapabilityStatus
    description: str
    request_model: Type[BaseModel]
    response_model: Type[BaseModel]
    agent_api_method: str   # GET / POST / PATCH / PUT / DELETE
    agent_api_path: str    # e.g. /api/agent/v1/projects
    mcp_tool_name: str
    cli_command: str
    service_ref: str       # e.g. project_service.ProjectService.create
    # Some transport-specific capabilities (for example SSE streams) cannot
    # be represented as an MCP request/response tool invocation.
    mcp_enabled: bool = True
    destructive: bool = False
    long_running: bool = False
    replaced_by: Optional[str] = None
    # Increment even when only semantics (not JSON shape) change.
    behavior_version: str = "2"
    # Declared transport kind: "json" (invoke-able), "binary" (byte stream),
    # "event_stream" (SSE), "file_upload" (multipart request, JSON reply).
    # Non-json transports are HTTP-only; discovery reports invocable=false.
    transport: str = "json"
