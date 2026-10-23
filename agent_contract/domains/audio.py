"""Agent audio-domain declarations: visible Step 5 narration, TTS and media settings.

自由载荷用 ``FreeFormRequest`` 信封；响应跟随业务服务返回结构（free object），
关键字段在描述里说明。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from agent_contract.registry import AgentCapability, CapabilityStatus
from agent_contract.domains.freeform import FreeFormRequest, OptionalFreeFormRequest


class NarrationResultUpdateRequest(BaseModel):
    payload: Dict[str, Any] = Field(..., description="Step 6 旁白结果载荷；由 narration_service 校验")


class TtsAudioConfirmRequest(BaseModel):
    payload: Optional[Dict[str, Any]] = Field(None, description="音频确认参数（哈希校验等）")


class MediaSettingsUpdateRequest(BaseModel):
    payload: Dict[str, Any] = Field(..., description="背景/字幕设置载荷；由 visual_settings_service 校验")


CAPABILITIES = [
    AgentCapability(
        id="narration.init", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Initialize Step 6 narration beats from the current Visual Contract.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/narration/init",
        mcp_tool_name="ppt_narration_init", cli_command="narration init",
        service_ref="narration_service.init_step6_narration",
    ),
    AgentCapability(
        id="narration.result.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the stored Step 6 narration result (per-slide narration beats and sources).",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/narration",
        mcp_tool_name="ppt_narration_result_get", cli_command="narration show",
        service_ref="narration_service.get_step6_result",
    ),
    AgentCapability(
        id="narration.result.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Save the Step 6 narration result; semantic changes retain the audio confirmation record for hash revalidation, identical saves are no-ops.",
        request_model=NarrationResultUpdateRequest, response_model=BaseModel,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/narration",
        mcp_tool_name="ppt_narration_result_update", cli_command="narration update-result",
        service_ref="narration_service.update_step6_result",
    ),
    AgentCapability(
        id="narration.repair", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Explicitly repair/normalize the stored narration result without mutating on read.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/narration/repair",
        mcp_tool_name="ppt_narration_repair", cli_command="narration repair",
        service_ref="narration_service.repair_step6_result",
    ),
    AgentCapability(
        id="narration.annotation_settings.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the global AI narration-annotation prompt settings.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/narration-annotation/settings",
        mcp_tool_name="ppt_narration_annotation_settings_get", cli_command="narration annotation-settings",
        service_ref="narration_service.get_narration_annotation_settings",
    ),
    AgentCapability(
        id="narration.annotation_settings.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Update the global AI narration-annotation prompt settings.",
        request_model=FreeFormRequest, response_model=BaseModel,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/narration-annotation/settings",
        mcp_tool_name="ppt_narration_annotation_settings_update", cli_command="narration annotation-settings --set",
        service_ref="narration_service.update_narration_annotation_settings",
    ),
    AgentCapability(
        id="narration.annotate", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Run the AI narration annotation LLM call synchronously; uses the configured provider and the cooperative stop signal.",
        request_model=OptionalFreeFormRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/narration/annotate",
        mcp_tool_name="ppt_narration_annotate", cli_command="narration annotate",
        service_ref="narration_service.annotate_step6_narration",
        long_running=True,
    ),
    AgentCapability(
        id="tts.sync_synthesize", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Legacy synchronous TTS synthesis kept in parity with the business route; Agents should prefer tts.synthesize which returns a durable operation_id.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/tts/sync",
        mcp_tool_name="ppt_tts_sync_synthesize", cli_command="tts synthesize-sync",
        service_ref="tts_service.synthesize_tts_resumable",
        long_running=True,
    ),
    AgentCapability(
        id="tts.audio_status.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read per-slide TTS audio status including freshness and confirmation state.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/tts/audio-status",
        mcp_tool_name="ppt_tts_audio_status_get", cli_command="tts audio-status",
        service_ref="tts_service.get_tts_audio_status",
    ),
    AgentCapability(
        id="tts.audio.confirm", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Confirm generated slide audio; confirmation validates artifact hashes and is required before rendering.",
        request_model=TtsAudioConfirmRequest, response_model=BaseModel,
        agent_api_method="POST", agent_api_path="/api/agent/v1/projects/{project_id}/tts/confirm",
        mcp_tool_name="ppt_tts_audio_confirm", cli_command="tts confirm",
        service_ref="tts_service.confirm_tts_audio",
    ),
    AgentCapability(
        id="media.background.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read the project video-background settings and their manifest synchronization state.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/media/background",
        mcp_tool_name="ppt_media_background_get", cli_command="media background",
        service_ref="visual_settings_service.VisualSettingsService.get",
    ),
    AgentCapability(
        id="media.background.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Update project video-background settings; downstream invalidation follows the registered impact rules.",
        request_model=MediaSettingsUpdateRequest, response_model=BaseModel,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/media/background",
        mcp_tool_name="ppt_media_background_update", cli_command="media background --set",
        service_ref="visual_settings_service.VisualSettingsService.update_background",
    ),
    AgentCapability(
        id="media.subtitles.get", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Read project subtitle settings (font, color, position) with preview selection.",
        request_model=BaseModel, response_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/projects/{project_id}/media/subtitles",
        mcp_tool_name="ppt_media_subtitles_get", cli_command="media subtitles",
        service_ref="visual_settings_service.VisualSettingsService.get_subtitles",
    ),
    AgentCapability(
        id="media.subtitles.update", version="1.0", behavior_version="1",
        status=CapabilityStatus.stable,
        description="Update project subtitle settings; identical saves are no-ops.",
        request_model=MediaSettingsUpdateRequest, response_model=BaseModel,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/projects/{project_id}/media/subtitles",
        mcp_tool_name="ppt_media_subtitles_update", cli_command="media subtitles --set",
        service_ref="visual_settings_service.VisualSettingsService.update_subtitles",
    ),
]
