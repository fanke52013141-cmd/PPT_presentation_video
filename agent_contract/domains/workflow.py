"""Read-only workflow observation contracts."""

from typing import Any

from pydantic import BaseModel, Field


class WorkflowStage(BaseModel):
    id: str
    visible_step: int
    internal_steps: list[int]
    required: bool = True
    skipped: bool = False
    recorded_status: dict[str, str]
    checks: dict[str, list[str]] = Field(default_factory=dict)
    module_state: str | None = None


class WorkflowAction(BaseModel):
    capability_id: str
    arguments: dict[str, Any]
    requires_input: bool = False


class ProjectStateResult(BaseModel):
    project_id: str
    revision: int
    observation_revision: str
    resource_versions: dict[str, str | None]
    stages: list[WorkflowStage]
    render_submission: dict[str, Any]
    pending_impacts: list[dict[str, Any]]
    allowed_actions: list[WorkflowAction]
