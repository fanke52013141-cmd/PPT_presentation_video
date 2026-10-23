"""Agent system request and response contracts."""

from __future__ import annotations

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


GenerationKind = Literal['storyboard_script', 'storyboard_visual', 'mask', 'tts', 'video']


class GenerationStopRequest(BaseModel):
    operation_id: str = Field(min_length=1, max_length=128)


class GenerationControlResult(BaseModel):
    active: bool
    operation_id: Optional[str] = None
    stop_requested: bool = False


class GenerationStopResult(BaseModel):
    accepted: bool
    operation_id: str
    message: str


class IdentityResult(BaseModel):
    account_id: str
    account_name: str
    scopes: list[str] = Field(default_factory=list)
    authenticated: bool = False


class DiagnosticsResult(BaseModel):
    agent_api_version: str
    contract_hash: str
    application_version: str = ""
    capabilities: list[str] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# 横向配置域能力声明（全局设置、凭据、模型连接、诊断）
# ---------------------------------------------------------------------------

from agent_contract.registry import AgentCapability, CapabilityStatus  # noqa: E402
from agent_contract.domains.freeform import FreeFormRequest  # noqa: E402


class CredentialUpdateRequest(BaseModel):
    credential_ref: str = Field(..., description="凭据引用（如 llm/openai）")
    payload: dict[str, Any] = Field(..., description="凭据更新载荷；凭据值只写不读")


class ConnectionsListRequest(BaseModel):
    kind: Optional[str] = None
    include_archived: bool = False


class ErrorLogRequest(BaseModel):
    limit: int = Field(50, ge=1, le=500)


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
        id="settings.get",
        description="Read masked global settings; credentials are never returned in clear text.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/settings",
        cli_command="settings show",
        service_ref="settings_service.get_settings",
    ),
    _cap(
        id="settings.update",
        description="Update global settings; masked placeholders preserve stored secrets.",
        request_model=FreeFormRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/settings",
        cli_command="settings --set",
        service_ref="settings_service.update_system_settings",
    ),
    _cap(
        id="settings.config.export",
        description="Export the portable configuration package (secrets stripped).",
        agent_api_method="GET", agent_api_path="/api/agent/v1/config/export",
        cli_command="settings config-export",
        service_ref="settings_routes.export_full_config",
    ),
    _cap(
        id="settings.config.export.zip",
        description="Export the portable configuration package as a ZIP byte stream.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/config/export-zip",
        cli_command="settings config-export-zip",
        service_ref="settings_routes.export_full_config_zip",
        transport="binary",
        mcp_enabled=False,
    ),
    _cap(
        id="settings.config.export.secrets",
        description="Export the configuration package including secrets (JSON).",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/config/export-with-secrets",
        cli_command="settings config-export-secrets",
        service_ref="settings_routes.export_full_config_with_secrets",
    ),
    _cap(
        id="settings.config.export.secrets.zip",
        description="Export the configuration package including secrets as a ZIP byte stream.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/config/export-with-secrets-zip",
        cli_command="settings config-export-secrets-zip",
        service_ref="settings_routes.export_full_config_with_secrets_zip",
        transport="binary",
        mcp_enabled=False,
    ),
    _cap(
        id="settings.config.import",
        description="Import a configuration package; every image reference is validated before any write.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/config/import",
        cli_command="settings config-import",
        service_ref="settings_routes.import_full_config",
    ),
    _cap(
        id="settings.config.import.zip",
        description="Import a configuration package from an uploaded ZIP (multipart/form-data).",
        agent_api_method="POST", agent_api_path="/api/agent/v1/config/import-zip",
        cli_command="settings config-import-zip",
        service_ref="settings_routes.import_full_config_zip",
        transport="file_upload",
        mcp_enabled=False,
    ),
    _cap(
        id="settings.llm.test",
        description="Test the LLM connection with the supplied credentials; never stores them.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/settings/test-llm",
        cli_command="settings test-llm",
        service_ref="settings_service.test_llm_connection",
    ),
    _cap(
        id="settings.image.test",
        description="Test the image provider connection with the supplied credentials.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/settings/test-image",
        cli_command="settings test-image",
        service_ref="settings_service.test_image_connection",
    ),
    _cap(
        id="settings.tts.test",
        description="Test the TTS provider connection with the supplied credentials.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/settings/test-tts",
        cli_command="settings test-tts",
        service_ref="settings_service.test_tts_connection",
    ),
    _cap(
        id="settings.comfyui_workflow.get",
        description="Read the global ComfyUI TTS workflow template.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/settings/comfyui-tts-workflow",
        cli_command="settings comfyui-workflow",
        service_ref="settings_routes.get_comfyui_tts_workflow",
    ),
    _cap(
        id="settings.comfyui_workflow.upload",
        description="Upload a global ComfyUI TTS workflow template (multipart/form-data).",
        agent_api_method="POST", agent_api_path="/api/agent/v1/settings/comfyui-tts-workflow",
        cli_command="settings comfyui-workflow-upload",
        service_ref="settings_routes.upload_comfyui_tts_workflow",
        transport="file_upload",
        mcp_enabled=False,
    ),
    _cap(
        id="credentials.list",
        description="List credential references (query: include_disabled); secret values stay masked.",
        request_model=BaseModel,
        agent_api_method="GET", agent_api_path="/api/agent/v1/credentials",
        cli_command="credentials list",
        service_ref="credential_routes.list_credentials",
    ),
    _cap(
        id="credentials.create",
        description="Create a credential reference; the secret travels once and is stored hashed.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/credentials",
        cli_command="credentials create",
        service_ref="credential_routes.create_credential",
    ),
    _cap(
        id="credentials.update",
        description="Update one credential by reference; omitted secret fields are preserved.",
        request_model=CredentialUpdateRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/credentials",
        cli_command="credentials --set",
        service_ref="credential_routes.update_credential",
    ),
    _cap(
        id="connections.list",
        description="List saved model connections (query: kind, include_archived).",
        request_model=ConnectionsListRequest,
        agent_api_method="GET", agent_api_path="/api/agent/v1/model-connections",
        cli_command="connections list",
        service_ref="model_connection_routes.list_model_connections",
    ),
    _cap(
        id="connections.create",
        description="Create a saved model connection.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/model-connections",
        cli_command="connections create",
        service_ref="model_connection_routes.create_model_connection"
    ),
    _cap(
        id="connections.get",
        description="Read one saved model connection with masked credentials.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/model-connections/{connection_id}",
        cli_command="connections show",
        service_ref="model_connection_routes.get_model_connection",
    ),
    _cap(
        id="connections.update",
        description="Update one saved model connection.",
        request_model=FreeFormRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/model-connections/{connection_id}",
        cli_command="connections --set",
        service_ref="model_connection_routes.update_model_connection",
    ),
    _cap(
        id="connections.reference_audio.upload",
        description="Upload reference audio for a TTS connection (multipart/form-data).",
        agent_api_method="POST", agent_api_path="/api/agent/v1/model-connections/{connection_id}/reference-audio",
        cli_command="connections reference-audio-upload",
        service_ref="model_connection_routes.upload_model_reference_audio",
        transport="file_upload",
        mcp_enabled=False,
    ),
    _cap(
        id="connections.copy",
        description="Copy one saved model connection.",
        request_model=FreeFormRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/model-connections/{connection_id}/copy",
        cli_command="connections copy",
        service_ref="model_connection_routes.copy_model_connection",
    ),
    _cap(
        id="connections.test",
        description="Test one saved model connection end to end.",
        agent_api_method="POST", agent_api_path="/api/agent/v1/model-connections/{connection_id}/test",
        cli_command="connections test",
        service_ref="model_connection_routes.test_saved_model_connection",
    ),
    _cap(
        id="connections.state.update",
        description="Archive/restore or toggle one saved model connection.",
        request_model=FreeFormRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/model-connections/{connection_id}/state",
        cli_command="connections state --set",
        service_ref="model_connection_routes.update_model_connection_state",
    ),
    _cap(
        id="connections.delete",
        description="Delete one saved model connection. Destructive.",
        destructive=True,
        agent_api_method="DELETE", agent_api_path="/api/agent/v1/model-connections/{connection_id}",
        cli_command="connections delete",
        service_ref="model_connection_routes.delete_model_connection",
    ),
    _cap(
        id="diagnostics.runtime",
        description="Read runtime diagnostics for the current process.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/runtime/diagnostics",
        cli_command="diagnostics runtime",
        service_ref="diagnostics_routes.runtime_diagnostics",
    ),
    _cap(
        id="diagnostics.governor",
        description="Read the generation governor snapshot (gateway quotas and queues).",
        agent_api_method="GET", agent_api_path="/api/agent/v1/diagnostics/generation-governor",
        cli_command="diagnostics governor",
        service_ref="diagnostics_routes.generation_governor_snapshot",
    ),
    _cap(
        id="diagnostics.error_log",
        description="Read recent pipeline error log entries (query: limit).",
        request_model=ErrorLogRequest,
        agent_api_method="GET", agent_api_path="/api/agent/v1/error-log",
        cli_command="diagnostics error-log",
        service_ref="diagnostics_routes.get_error_log",
    ),
    _cap(
        id="diagnostics.error_log.latest",
        description="Read the latest error log entry as plain text content (not a JSON tool result).",
        agent_api_method="GET", agent_api_path="/api/agent/v1/error-log/latest",
        cli_command="diagnostics latest-error",
        service_ref="diagnostics_routes.get_latest_error_log",
        transport="binary",
        mcp_enabled=False,
    ),
]
