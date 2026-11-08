"""Agent digital_human request and response contracts."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from digital_human_contracts import (
    DigitalHumanMode,
    DigitalHumanMotionSource,
    DigitalHumanShortVideoPolicy,
)
from agent_contract.registry import AgentCapability, CapabilityStatus
from agent_contract.domains.freeform import FreeFormRequest, OptionalFreeFormRequest


class DigitalHumanCircle(BaseModel):
    """Presenter window circle: page position and relative size."""

    cx: float = Field(0.85, description="窗口圆心横向位置（0-1 页面比例）")
    cy: float = Field(0.76, description="窗口圆心纵向位置（0-1 页面比例）")
    r: float = Field(0.12, description="窗口半径（相对页面宽度）")


class DigitalHumanVideoLayout(BaseModel):
    """Presenter video placement inside the window."""

    ox: float = Field(0.5, description="视频横向偏移")
    oy: float = Field(0.5, description="视频纵向偏移")
    zoom: float = Field(1.0, description="视频缩放")


class DigitalHumanConfigPatch(BaseModel):
    """Partial digital-human configuration patch (only supplied fields change).

    The service remains the source of truth for normalization and business
    validation; this schema makes the accepted fields, defaults and enum values
    discoverable before an Agent calls the capability.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: Optional[bool] = Field(
        None, description="是否启用数字人讲解；短视频/成品视频模式下同样需要开启才会合成",
    )
    mode: Optional[DigitalHumanMode] = Field(
        None,
        description=(
            "portrait=照片+动作视频（默认）；upload=直传成品视频；"
            "comfyui/generate 为旧模式兼容"
        ),
    )
    motion_source: Optional[DigitalHumanMotionSource] = Field(
        None, description="动作来源：default=平台内置模板，custom=项目上传的动作视频",
    )
    upload_start_sec: Optional[float] = Field(
        None, ge=0, description="upload 模式从成品视频的第几秒开始取画面（默认 0）",
    )
    upload_short_video_policy: Optional[DigitalHumanShortVideoPolicy] = Field(
        None,
        description="upload 模式视频短于旁白时：reject=拒绝（默认），loop=循环",
    )
    shape: Optional[str] = Field(
        None,
        description="窗口形状 circle | rect；非法值由服务端归一为 circle（与 Web 一致）",
    )
    avatar_id: Optional[str] = Field(
        None, description="项目已上传并通过校验的讲师形象 ID",
    )
    sync_mode: Optional[str] = Field(
        None, description="口型同步模式（例如 accurate）",
    )
    position: Optional[dict[str, Any]] = Field(
        None, description="讲师窗口位置覆盖（可选）",
    )
    border: Optional[dict[str, Any]] = Field(
        None, description="讲师窗口描边（可选，默认 width=2 color=#FFFFFF）",
    )
    circle: Optional[DigitalHumanCircle] = Field(
        None, description="圆形/矩形窗口位置与大小",
    )
    video: Optional[DigitalHumanVideoLayout] = Field(
        None, description="窗口内视频的偏移与缩放",
    )


class DigitalHumanConfigView(BaseModel):
    """Effective normalized digital-human configuration as stored."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = False
    mode: str = "portrait"
    motion_source: str = "default"
    upload_start_sec: float = 0.0
    upload_short_video_policy: str = "reject"
    shape: str = "circle"
    avatar_id: str = ""
    sync_mode: str = "accurate"
    circle: DigitalHumanCircle = Field(default_factory=DigitalHumanCircle)
    video: DigitalHumanVideoLayout = Field(default_factory=DigitalHumanVideoLayout)
    position: Optional[dict[str, Any]] = None
    border: Optional[dict[str, Any]] = None


class DigitalHumanMotionSummary(BaseModel):
    """Current driving-motion source state."""

    source: str = Field("default", description="default | custom")
    exists: bool = Field(False, description="动作视频是否存在且可解码")
    metadata: Optional[dict[str, Any]] = Field(
        None, description="解码后的视频元数据（宽/高/时长），不存在时为 null",
    )


class DigitalHumanConfigUpdateRequest(BaseModel):
    """Validated Agent transport envelope for the project digital-human config."""

    config: DigitalHumanConfigPatch = Field(
        ...,
        description="数字人配置补丁；只提交需要修改的字段，未提交字段保持原值",
    )


class DigitalHumanConfigResult(BaseModel):
    config: DigitalHumanConfigView = Field(default_factory=DigitalHumanConfigView)
    slides: dict[str, dict[str, Any]] = Field(default_factory=dict)
    audio_ready: dict[str, bool] = Field(default_factory=dict)
    audio_ready_count: int = 0
    total_slides: int = 0
    upload_video_exists: bool = False
    motion: DigitalHumanMotionSummary = Field(default_factory=DigitalHumanMotionSummary)


class DigitalHumanHealthResult(BaseModel):
    """Digital-human service health, including the portrait pipeline readiness."""

    available: bool = True
    model_ready: bool = Field(False, description="任一已配置生成后端是否就绪")
    portrait_model_ready: bool = Field(
        False, description="LivePortrait + MuseTalk 照片动作迁移环境是否就绪",
    )
    comfyui_online: bool = False
    default_motion_available: bool = Field(
        False, description="平台默认动作模板是否存在",
    )
    inference_backend: str = ""
    health: dict[str, Any] = Field(
        default_factory=dict, description="数字人服务返回的原始健康载荷",
    )
    error: str = Field("", description="服务不可用时的错误文本")


def _cap(**kwargs) -> AgentCapability:
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
        id="digital_human.motion.upload",
        version="1.1",
        behavior_version="2",
        description=(
            "Upload the project's custom driving video for portrait motion "
            "transfer (multipart/form-data; identical bytes are a no-op). "
            "HTTP/SDK file transport only: not invocable through MCP."
        ),
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/motion",
        cli_command="digital-human upload-motion",
        service_ref="digital_human_routes.upload_dh_motion",
        transport="file_upload", mcp_enabled=False,
    ),
    _cap(
        id="digital_human.slide.generate",
        version="1.1",
        behavior_version="3",
        description=(
            "Generate the digital-human presenter video for one slide. portrait mode "
            "requires the selected photo, an available driving motion source and "
            "confirmed course audio; upload mode rejects generation (use "
            "digital_human.video.upload); legacy comfyui/generate follow the "
            "configured backend. Long-running."
        ),
        request_model=OptionalFreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/generate",
        cli_command="digital-human generate-slide",
        service_ref="digital_human_routes.generate_dh",
        long_running=True,
    ),
    _cap(
        id="digital_human.jobs.get",
        version="1.3",
        behavior_version="5",
        description=(
            "Read one digital-human generation job by id. waiting_external, "
            "publishing and submission_unknown are non-terminal; stale marks a "
            "result built from changed photo, motion or audio sources."
        ),
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/jobs/{job_id}",
        cli_command="digital-human job",
        service_ref="digital_human_routes.get_dh_job",
    ),
    _cap(
        id="digital_human.slide_video.get",
        description="Download one slide's digital-human video as binary content.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/video",
        cli_command="digital-human slide-video",
        service_ref="digital_human_routes.get_dh_slide_video",
        transport="binary",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.slide.compose", behavior_version="2",
        description="Compose the slide video with the digital-human presenter overlay.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/compose",
        cli_command="digital-human compose",
        service_ref="digital_human_routes.compose_dh_slide",
        long_running=True,
    ),
    _cap(
        id="digital_human.composite_video.get",
        description="Download one slide's composed digital-human overlay video as binary content.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/slides/{slide_id}/composite-video",
        cli_command="digital-human composite-video",
        service_ref="digital_human_routes.get_dh_composite_video",
        transport="binary",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.audio.export", version="1.1", behavior_version="2",
        description="Export the full digital-human narration audio for the project.",
        request_model=OptionalFreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/export-audio",
        cli_command="digital-human export-audio",
        service_ref="digital_human_routes.export_full_audio",
        long_running=True,
    ),
    _cap(
        id="digital_human.audio.file",
        description="Download the exported full audio file as binary content.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/export-audio/content",
        cli_command="digital-human audio",
        service_ref="digital_human_routes.get_full_audio",
        transport="binary",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.video.upload", version="1.1", behavior_version="2",
        description="Upload one digital-human presenter video (multipart/form-data).",
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/upload",
        cli_command="digital-human upload-video",
        service_ref="digital_human_routes.upload_dh_video",
        transport="file_upload",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.video.uploaded.get",
        description="Download the uploaded digital-human presenter video as binary content.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/upload/content",
        cli_command="digital-human uploaded-video",
        service_ref="digital_human_routes.get_dh_upload_video",
        transport="binary",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.avatars.upload", behavior_version="2",
        description="Upload one digital-human avatar image (multipart/form-data).",
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/avatars/upload",
        cli_command="digital-human upload-avatar",
        service_ref="digital_human_routes.upload_dh_avatar",
        transport="file_upload",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.avatars.list", behavior_version="2",
        description="List uploaded digital-human avatars.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/avatars",
        cli_command="digital-human avatars",
        service_ref="digital_human_routes.list_dh_avatars",
    ),
    _cap(
        id="digital_human.workflow.upload",
        description="Upload a ComfyUI workflow template for digital-human generation (multipart/form-data).",
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/workflow/upload",
        cli_command="digital-human upload-workflow",
        service_ref="digital_human_routes.upload_comfyui_workflow",
        transport="file_upload",
        mcp_enabled=False,
    ),
    _cap(
        id="digital_human.workflow.get",
        description="Read the project ComfyUI workflow template state.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/digital-human/workflow",
        cli_command="digital-human workflow",
        service_ref="digital_human_routes.get_comfyui_workflow",
    ),
]
