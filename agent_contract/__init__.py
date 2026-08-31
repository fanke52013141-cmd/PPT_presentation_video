"""Agent contract package — the single source of truth for Agent-facing capabilities.

This package exports:
- Pydantic request/response models for every Agent operation.
- The AgentCapability registry that maps capabilities to services, MCP tools,
  CLI commands, and API endpoints.
- Unified Operation and Artifact models for long-running tasks and produced files.
- Version and compatibility metadata.
"""

from agent_contract.models import (
    ProjectCreateRequest, ProjectCreateResult,
    ProjectListRequest, ProjectListResult,
    ProjectGetResult, ProjectUpdateRequest, ProjectUpdateResult,
    SourceSetRequest, SourceSetResult,
    PipelineRunRequest, PipelineRunResult,
    PipelineStatusResult, PipelineResumeRequest,
    StageGetResult, NarrationUpdateRequest,
    ImageRegenerateRequest, ImageRegenerateResult,
    TtsSynthesizeRequest, TtsSynthesizeResult,
    VideoRenderRequest, VideoRenderResult,
    CheckpointApproveRequest, CheckpointResult,
    ArtifactsListRequest, ArtifactsListResult,
    ArtifactGetResult,
    DiagnosticsResult,
)
from agent_contract.operations import (
    OperationStatus, OperationResult,
    CHECKPOINT_STAGES,
)
from agent_contract.artifacts import (
    ArtifactType, ArtifactInfo, ArtifactCollection,
)
from agent_contract.capabilities import (
    CAPABILITIES, get_capability, get_stable_capabilities,
    AgentCapability, CapabilityStatus,
)
from agent_contract.versions import (
    AGENT_API_VERSION, CONTRACT_VERSION, get_contract_hash,
    get_capability_versions, get_meta,
)

__all__ = [
    # Models
    "ProjectCreateRequest", "ProjectCreateResult",
    "ProjectListRequest", "ProjectListResult",
    "ProjectGetResult", "ProjectUpdateRequest", "ProjectUpdateResult",
    "SourceSetRequest", "SourceSetResult",
    "PipelineRunRequest", "PipelineRunResult",
    "PipelineStatusResult", "PipelineResumeRequest",
    "StageGetResult", "NarrationUpdateRequest",
    "ImageRegenerateRequest", "ImageRegenerateResult",
    "TtsSynthesizeRequest", "TtsSynthesizeResult",
    "VideoRenderRequest", "VideoRenderResult",
    "CheckpointApproveRequest", "CheckpointResult",
    "ArtifactsListRequest", "ArtifactsListResult",
    "ArtifactGetResult",
    "DiagnosticsResult",
    # Operations
    "OperationStatus", "OperationResult",
    "CHECKPOINT_STAGES",
    # Artifacts
    "ArtifactType", "ArtifactInfo", "ArtifactCollection",
    # Capabilities
    "CAPABILITIES", "get_capability", "get_stable_capabilities",
    "AgentCapability", "CapabilityStatus",
    # Versions
    "AGENT_API_VERSION", "CONTRACT_VERSION", "get_contract_hash",
    "get_capability_versions", "get_meta",
]
