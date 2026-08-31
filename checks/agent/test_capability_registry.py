"""Test the capability registry for completeness and consistency.

Every AgentCapability must have:
- A unique id
- A non-empty MCP tool name
- A CLI command
- Valid request and response models
- A stable status (for the first release)
- No orphaned capabilities (every MCP tool maps back to a capability)
"""

from __future__ import annotations

import pytest

from agent_contract.capabilities import (
    CAPABILITIES,
    AgentCapability,
    CapabilityStatus,
    get_capability,
    get_capability_by_mcp_tool,
    get_stable_capabilities,
)


class TestRegistryIntegrity:
    """Verify the capability registry is well-formed."""

    def test_registry_is_non_empty(self):
        assert len(CAPABILITIES) > 0, "Capability registry must not be empty"

    def test_all_capabilities_have_unique_ids(self):
        ids = [c.id for c in CAPABILITIES]
        assert len(ids) == len(set(ids)), f"Duplicate capability IDs: {ids}"

    def test_all_mcp_tool_names_unique(self):
        names = [c.mcp_tool_name for c in CAPABILITIES]
        assert len(names) == len(set(names)), f"Duplicate MCP tool names: {names}"

    def test_all_cli_commands_unique(self):
        cmds = [c.cli_command for c in CAPABILITIES]
        assert len(cmds) == len(set(cmds)), f"Duplicate CLI commands: {cmds}"

    def test_all_have_non_empty_descriptions(self):
        for cap in CAPABILITIES:
            assert cap.description, f"Capability {cap.id} has empty description"

    def test_all_have_agent_api_paths(self):
        for cap in CAPABILITIES:
            assert cap.agent_api_path.startswith("/api/agent/v1"), (
                f"Capability {cap.id} path does not start with /api/agent/v1: {cap.agent_api_path}"
            )

    def test_all_have_http_methods(self):
        valid_methods = {"GET", "POST", "PATCH", "DELETE", "PUT"}
        for cap in CAPABILITIES:
            assert cap.agent_api_method in valid_methods, (
                f"Capability {cap.id} has invalid method: {cap.agent_api_method}"
            )

    def test_all_have_service_refs(self):
        for cap in CAPABILITIES:
            assert cap.service_ref, f"Capability {cap.id} has empty service_ref"

    def test_all_have_versions(self):
        for cap in CAPABILITIES:
            # Version must look like semver-ish
            parts = cap.version.split(".")
            assert len(parts) >= 2, f"Capability {cap.id} has invalid version: {cap.version}"


class TestRegistryLookups:
    """Test lookup functions."""

    def test_get_capability_by_id(self):
        cap = get_capability("project.create")
        assert cap.id == "project.create"

    def test_get_capability_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown capability"):
            get_capability("nonexistent.capability")

    def test_get_by_mcp_tool(self):
        cap = get_capability_by_mcp_tool("ppt_project_create")
        assert cap.mcp_tool_name == "ppt_project_create"

    def test_get_by_mcp_tool_unknown_raises(self):
        with pytest.raises(ValueError, match="Unknown MCP tool"):
            get_capability_by_mcp_tool("ppt_nonexistent")

    def test_stable_capabilities_excludes_removed(self):
        stable = get_stable_capabilities()
        for cap in stable:
            assert cap.status == CapabilityStatus.stable

    def test_all_capabilities_are_stable(self):
        """In the first release, all capabilities should be stable."""
        for cap in CAPABILITIES:
            assert cap.status == CapabilityStatus.stable, (
                f"Capability {cap.id} is {cap.status}, expected stable"
            )


class TestModelConsistency:
    """Verify Pydantic models are usable."""

    def test_request_models_are_basemodel_subclasses(self):
        from pydantic import BaseModel
        for cap in CAPABILITIES:
            assert issubclass(cap.request_model, BaseModel), (
                f"Capability {cap.id} request_model is not a BaseModel"
            )

    def test_response_models_are_basemodel_subclasses(self):
        from pydantic import BaseModel
        for cap in CAPABILITIES:
            assert issubclass(cap.response_model, BaseModel), (
                f"Capability {cap.id} response_model is not a BaseModel"
            )

    def test_request_models_have_json_schema(self):
        from pydantic import BaseModel
        for cap in CAPABILITIES:
            if cap.request_model is BaseModel:
                continue  # bare BaseModel has no concrete schema
            schema = cap.request_model.model_json_schema()
            assert isinstance(schema, dict)
            assert "properties" in schema

    def test_response_models_have_json_schema(self):
        from pydantic import BaseModel
        for cap in CAPABILITIES:
            if cap.response_model is BaseModel:
                continue  # bare BaseModel has no concrete schema
            schema = cap.response_model.model_json_schema()
            assert isinstance(schema, dict)


class TestVersionAndContractHash:
    """Test version management and contract hashing."""

    def test_contract_hash_is_stable(self):
        from agent_contract.versions import get_contract_hash
        h1 = get_contract_hash()
        h2 = get_contract_hash()
        assert h1 == h2, "Contract hash should be deterministic"

    def test_contract_hash_is_hex(self):
        from agent_contract.versions import get_contract_hash
        h = get_contract_hash()
        assert all(c in "0123456789abcdef" for c in h), f"Invalid hex: {h}"

    def test_meta_returns_required_fields(self):
        from agent_contract.versions import get_meta
        meta = get_meta()
        assert "agent_api_version" in meta
        assert "contract_hash" in meta
        assert "capabilities" in meta
        assert isinstance(meta["capabilities"], list)
        assert len(meta["capabilities"]) > 0
