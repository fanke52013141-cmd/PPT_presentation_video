"""Unified Pydantic models for all Agent-facing operations.

These models are the SINGLE source of truth for request/response schemas.
Agent API, MCP tools, and CLI commands all reference these models — never
duplicate parameter definitions across layers.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Project models
# ---------------------------------------------------------------------------

class CanvasProfile(str, Enum):
    landscape_16_9 = "landscape_16_9"
    portrait_9_16 = "portrait_9_16"


class AutomationMode(str, Enum):
    auto = "auto"
    manual = "manual"
    agent = "agent"


class ReviewPolicy(str, Enum):
    none = "none"
    images_and_video = "images_and_video"
    all_stages = "all_stages"


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="项目名称")
    description: str = Field("", max_length=2000, description="项目描述")
    canvas_profile: CanvasProfile = CanvasProfile.landscape_16_9
    automation_mode: AutomationMode = AutomationMode.auto
    review_policy: ReviewPolicy = ReviewPolicy.none
    mask_enabled: bool = Field(True, description="是否启用 Mask 标注；False 时流水线跳过 AI Mask 与 Reveal 资源构建，按整页切换渲染")
    config_package_id: Optional[str] = Field(None, min_length=1, max_length=120, description="创作配置包 ID")
    config_package_version: Optional[int] = Field(None, ge=1, description="创作配置包版本；不填时固定当前最新版本")
    config_overrides: dict[str, Any] = Field(default_factory=dict, description="仅本项目的创作配置覆盖项")
    idempotency_key: Optional[str] = Field(None, description="幂等键，防止重复创建")


class ProjectSummary(BaseModel):
    project_id: str
    name: str
    description: str
    canvas_profile: str
    ai_mode: str
    current_step: int
    status: str
    step_status: dict[str, str] = Field(default_factory=dict)
    revision: int = Field(0, description="乐观锁版本号，每次写操作递增")
    review_policy: str = Field("none", description="审查策略: none / images_and_video / all_stages")
    mask_enabled: bool = Field(True, description="项目是否启用 Mask 标注（整页切换模式为 False）")
    creation_config: Optional[dict[str, Any]] = Field(None, description="项目固定使用的创作配置包版本摘要")
    created_at: Optional[str] = None


class ProjectCreateResult(BaseModel):
    project: ProjectSummary
    operation_id: str


class ProjectListRequest(BaseModel):
    status_filter: Optional[str] = Field(None, description="active / completed / all")
    limit: int = Field(50, ge=1, le=200)


class ProjectListResult(BaseModel):
    projects: list[ProjectSummary]
    total: int


class ProjectGetResult(BaseModel):
    project: ProjectSummary
    has_article: bool = False
    has_contract: bool = False
    slide_ids: list[str] = Field(default_factory=list)


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    ai_mode: Optional[str] = None
    expected_revision: Optional[int] = Field(None, description="乐观锁：期望的项目版本号")
    idempotency_key: Optional[str] = None


class ProjectUpdateResult(BaseModel):
    project: ProjectSummary
    updated: bool


# ---------------------------------------------------------------------------
# Source / Article models
# ---------------------------------------------------------------------------

class SourceSetRequest(BaseModel):
    content: Optional[str] = Field(None, description="直接提供文章内容（Markdown）")
    topic: Optional[str] = Field(None, description="主题描述，触发 AI 生成文章")
    idempotency_key: Optional[str] = None


class SourceSetResult(BaseModel):
    project_id: str
    article_imported: bool
    article_preview: str = Field("", description="文章内容前 500 字")
    word_count: int = 0


# ---------------------------------------------------------------------------
# Pipeline run models
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Digital human
# ---------------------------------------------------------------------------

class DigitalHumanConfigUpdateRequest(BaseModel):
    """Validated Agent transport envelope for the project digital-human config."""

    config: dict[str, Any] = Field(
        ...,
        description="Digital-human configuration patch. Only supported fields are persisted.",
    )


class DigitalHumanConfigResult(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Stage models
# ---------------------------------------------------------------------------

class StageGetResult(BaseModel):
    project_id: str
    stage: str
    data: dict[str, Any] = Field(default_factory=dict)
    slide_ids: list[str] = Field(default_factory=list)


class NarrationUpdateRequest(BaseModel):
    slide_id: str
    narration_text: str
    expected_revision: Optional[int] = None
    idempotency_key: Optional[str] = None


class ImageRegenerateRequest(BaseModel):
    slide_id: str
    instruction: str = Field("", description="修改指令，如'更有冲击力'")
    idempotency_key: Optional[str] = None


class ImageRegenerateResult(BaseModel):
    slide_id: str
    artifact_id: str = ""
    resource_uri: str = ""
    revision: int = 0
    message: str = ""


# ---------------------------------------------------------------------------
# Media models
# ---------------------------------------------------------------------------

class TtsSynthesizeRequest(BaseModel):
    slide_ids: Optional[list[str]] = Field(None, description="指定 slide，None 表示全部")
    idempotency_key: Optional[str] = None


class TtsSynthesizeResult(BaseModel):
    operation_id: str
    project_id: str
    status: str
    job_id: str = ""


class VideoRenderRequest(BaseModel):
    idempotency_key: Optional[str] = None


class VideoRenderResult(BaseModel):
    operation_id: str
    project_id: str
    status: str
    job_id: str = ""


# ---------------------------------------------------------------------------
# Checkpoint models
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Artifact models
# ---------------------------------------------------------------------------

class ArtifactsListRequest(BaseModel):
    artifact_type: Optional[str] = Field(None, description="image / audio / video / pptx / all")
    slide_id: Optional[str] = None


class ArtifactInfo(BaseModel):
    artifact_id: str
    artifact_type: str
    filename: str
    mime_type: str
    size_bytes: int = 0
    resource_uri: str = ""
    slide_id: Optional[str] = None
    revision: int = 0
    created_at: Optional[str] = None


class ArtifactsListResult(BaseModel):
    project_id: str
    artifacts: list[ArtifactInfo]
    total: int


class ArtifactGetResult(BaseModel):
    artifact: ArtifactInfo
    download_url: str = ""


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

class DiagnosticsResult(BaseModel):
    agent_api_version: str
    contract_hash: str
    application_version: str = ""
    capabilities: list[str] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)
