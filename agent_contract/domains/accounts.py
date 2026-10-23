"""Agent account-domain declarations."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from agent_contract.registry import AgentCapability, CapabilityStatus


class AccountCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = None


class AccountProvisionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field("", max_length=2000)
    source_package_id: str = Field(..., min_length=1, max_length=120)
    source_package_version: Optional[int] = Field(None, ge=1)
    package_name: str = Field(..., min_length=1, max_length=200)
    package_description: str = Field("", max_length=2000)
    tags: List[str] = Field(default_factory=list)
    image_style_template_id: str = ""
    voice_id: str = ""
    storyboard_system_content: str = ""


class AccountRenameRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class AccountDefaultConfigRequest(BaseModel):
    package_id: Optional[str] = None
    version: Optional[str] = None


class AgentTokenRequest(BaseModel):
    name: str = Field("Agent", min_length=1, max_length=200)
    scopes: List[str] = Field(default_factory=list)


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
        id="accounts.list",
        description="List creative accounts visible to this connection.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/accounts",
        cli_command="accounts list",
        service_ref="account_routes.accounts",
    ),
    _cap(
        id="accounts.current",
        description="Read the account bound to this Agent connection.",
        agent_api_method="GET", agent_api_path="/api/agent/v1/accounts/current",
        cli_command="accounts current",
        service_ref="account_routes.current_account",
    ),
    _cap(
        id="accounts.create",
        description="Create a creative account; default creation configuration is set after switching.",
        request_model=AccountCreateRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/accounts",
        cli_command="accounts create",
        service_ref="account_routes.account_create",
    ),
    _cap(
        id="accounts.provision",
        description="Provision a ready-to-run account from the current one without exposing reused secrets.",
        request_model=AccountProvisionRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/accounts/provision",
        cli_command="accounts provision",
        service_ref="account_routes.account_provision_from_current",
    ),
    _cap(
        id="accounts.rename",
        description="Rename one account.",
        request_model=AccountRenameRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/accounts/{account_id}",
        cli_command="accounts rename",
        service_ref="account_routes.account_rename",
    ),
    _cap(
        id="accounts.delete",
        description="Delete one account and its scoped data. Destructive.",
        destructive=True,
        agent_api_method="DELETE", agent_api_path="/api/agent/v1/accounts/{account_id}",
        cli_command="accounts delete",
        service_ref="account_routes.account_delete",
    ),
    _cap(
        id="accounts.default_config.update",
        description="Set or clear one account's default creation configuration; the package must resolve inside that account.",
        request_model=AccountDefaultConfigRequest,
        agent_api_method="PUT", agent_api_path="/api/agent/v1/accounts/{account_id}/default-config",
        cli_command="accounts default-config",
        service_ref="account_routes.account_default_config",
    ),
    _cap(
        id="accounts.agent_token.create",
        description="Create one Agent token for the account; the token value is returned only at creation time.",
        request_model=AgentTokenRequest,
        agent_api_method="POST", agent_api_path="/api/agent/v1/accounts/{account_id}/agent-tokens",
        cli_command="accounts agent-token",
        service_ref="account_routes.account_agent_token",
    ),
]
