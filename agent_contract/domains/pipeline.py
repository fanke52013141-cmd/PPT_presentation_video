"""Agent pipeline request and response contracts."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class PipelineRunRequest(BaseModel):
    start_from: str = Field("preflight", description="起始阶段；未显式提供时按编排器恢复策略执行")
    stop_at: Optional[str] = Field(None, description="停止阶段，如 image_review")
    mode: str = Field("resume", description="resume / restart")
    idempotency_key: Optional[str] = None


class PipelineRunResult(BaseModel):
    operation_id: str
    project_id: str
    status: str
    current_stage: str
    message: str = ""


class PipelineStatusResult(BaseModel):
    operation_id: str
    project_id: str
    status: str
    current_stage: str
    progress: int = 0
    message: str = ""
    stages: list[dict[str, Any]] = Field(default_factory=list)
    blocking_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


class PipelineResumeRequest(BaseModel):
    stop_at: Optional[str] = None
    idempotency_key: Optional[str] = None


class StageGetResult(BaseModel):
    project_id: str
    stage: str
    data: dict[str, Any] = Field(default_factory=dict)
    slide_ids: list[str] = Field(default_factory=list)


class CheckpointApproveRequest(BaseModel):
    checkpoint: str = Field(..., description="storyboard_review / image_review / etc.")
    approved: bool = True
    notes: str = ""
    idempotency_key: Optional[str] = None


class CheckpointResult(BaseModel):
    project_id: str
    checkpoint: str
    approved: bool
    next_stage: str = ""


class CheckpointInfo(BaseModel):
    name: str
    label: str = ""
    description: str = ""


class CheckpointListResult(BaseModel):
    project_id: str
    checkpoints: list[CheckpointInfo] = Field(default_factory=list)
