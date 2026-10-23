"""Agent project request and response contracts."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field

from agent_contract.domains.freeform import FreeFormRequest


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


class ProductionMode(str, Enum):
    one_click = "one_click"
    guided = "guided"


class PresentationMode(str, Enum):
    full_frame = "full_frame"
    reveal = "reveal"


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="项目名称")
    description: str = Field("", max_length=2000, description="项目描述")
    canvas_profile: CanvasProfile = CanvasProfile.landscape_16_9
    automation_mode: AutomationMode = AutomationMode.auto
    review_policy: ReviewPolicy = ReviewPolicy.none
    mask_enabled: bool = Field(False, description="旧版兼容字段；新项目默认整页展示")
    production_mode: ProductionMode = ProductionMode.guided
    presentation_mode: PresentationMode = PresentationMode.full_frame
    config_package_id: Optional[str] = Field(None, min_length=1, max_length=120, description="创作配置包 ID")
    config_package_version: Optional[int] = Field(None, ge=1, description="创作配置包版本；不填时固定当前最新版本")
    config_overrides: dict[str, Any] = Field(default_factory=dict, description="仅本项目的创作配置覆盖项")
    course_id: Optional[str] = Field(None, min_length=1, max_length=120, description="项目所属课程 ID；不填则保留独立项目兼容模式")
    chapter_id: Optional[str] = Field(None, min_length=1, max_length=120, description="项目所属章节 ID；填写时服务端验证课程与账号归属")
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
    mask_enabled: bool = Field(False, description="旧版渲染兼容标记；由 presentation_mode 同步")
    production_mode: str = Field("guided", description="one_click / guided")
    presentation_mode: str = Field("full_frame", description="full_frame / reveal")
    creation_config: Optional[dict[str, Any]] = Field(None, description="项目固定使用的创作配置包版本摘要")
    course_id: Optional[str] = None
    chapter_id: Optional[str] = None
    created_at: Optional[str] = None


class ProjectCreateResult(BaseModel):
    project: ProjectSummary


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
    production_mode: Optional[ProductionMode] = None
    presentation_mode: Optional[PresentationMode] = None
    expected_revision: Optional[int] = Field(None, description="乐观锁：期望的项目版本号")
    idempotency_key: Optional[str] = None


class ProjectUpdateResult(BaseModel):
    project: ProjectSummary
    updated: bool


class ProjectDeleteResult(BaseModel):
    project_id: str
    deleted: bool
    details: dict[str, Any] = Field(default_factory=dict)


class ProjectDeleteRequest(BaseModel):
    expected_revision: Optional[int] = Field(None, ge=0, description="删除前核对的项目版本")
    idempotency_key: Optional[str] = Field(None, min_length=1, max_length=128)


class AiModeUpdateRequest(BaseModel):
    ai_mode: str = Field(..., description="auto 或 manual")
    expected_revision: Optional[int] = None


class StoryboardChangePreviewRequest(BaseModel):
    contract: dict[str, Any] = Field(..., description="提议的 Visual Contract 载荷；仅用于对比，不落盘")


def _cap(**kwargs):
    from agent_contract.registry import AgentCapability, CapabilityStatus

    kwargs.setdefault("version", "1.0")
    kwargs.setdefault("behavior_version", "1")
    kwargs.setdefault("status", CapabilityStatus.stable)
    kwargs.setdefault("request_model", BaseModel)
    kwargs.setdefault("response_model", BaseModel)
    kwargs["mcp_tool_name"] = "ppt_" + kwargs["id"].replace(".", "_")
    kwargs.setdefault("destructive", False)
    kwargs.setdefault("long_running", False)
    return AgentCapability(**kwargs)


CAPABILITIES = [
    _cap(
        id="project.impacts.get",
        description="Read registered downstream impacts for the project with their acknowledge state.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/impacts",
        cli_command="project impacts",
        service_ref="project_routes.get_project_impacts",
    ),
    _cap(
        id="project.impacts.reuse_preview",
        description="Preview which artifacts a storyboard reuse confirmation would keep or clear.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/impacts/storyboard-reuse-preview",
        cli_command="project reuse-preview",
        service_ref="project_routes.preview_storyboard_reuse",
    ),
    _cap(
        id="project.impacts.reuse_confirm",
        description="Confirm storyboard reuse after a profile switch, with explicit impact acknowledgement.",
        request_model=FreeFormRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/impacts/reuse-storyboard",
        cli_command="project reuse-confirm",
        service_ref="project_routes.confirm_storyboard_reuse",
    ),
    _cap(
        id="project.impacts.decision.update",
        description="Update one impact item's acknowledgement decision; does not override artifact freshness gates.",
        request_model=FreeFormRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/impacts/decision",
        cli_command="project impact-decision",
        service_ref="project_routes.update_project_impact_decision",
    ),
    _cap(
        id="project.impacts.image_reuse_confirm",
        description="Confirm image reuse after storyboard structure changes, with explicit impact acknowledgement.",
        request_model=FreeFormRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/impacts/reuse-image",
        cli_command="project image-reuse-confirm",
        service_ref="project_routes.confirm_storyboard_image_reuse",
    ),
    _cap(
        id="project.ai_mode.get",
        description="Read the project AI mode (auto/manual).",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/ai-mode",
        cli_command="project ai-mode",
        service_ref="project_routes.get_project_ai_mode",
    ),
    _cap(
        id="project.change_preview",
        description="Read-only what-if impact preview for a proposed Visual Contract edit; reuses the same pure diff as the commit path and reports the affected slides and expected downstream invalidation without writing anything.",
        request_model=StoryboardChangePreviewRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/change-preview",
        cli_command="project change-preview",
        service_ref="agent_workflow_service.preview_storyboard_change",
    ),
    _cap(
        id="project.ai_mode.update",
        description="Update the project AI mode (auto/manual).",
        request_model=AiModeUpdateRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/ai-mode",
        cli_command="project ai-mode --set",
        service_ref="project_routes.update_project_ai_mode",
    ),
]
