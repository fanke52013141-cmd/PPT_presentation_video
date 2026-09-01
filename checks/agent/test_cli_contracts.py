"""Test CLI contract alignment.

Verifies that:
1. CLI module imports correctly
2. CLI has subcommands matching the capability registry
3. CLI argument structure is valid
"""

from __future__ import annotations

import pytest

from agent_contract.capabilities import CAPABILITIES, CapabilityStatus


class TestCLIContract:
    """Verify CLI commands exist for all capabilities."""

    def test_cli_module_imports(self):
        """Ensure the CLI module can be imported without errors."""
        import importlib
        mod = importlib.import_module("cli.pptctl")
        assert mod is not None

    def test_cli_main_function_exists(self):
        import cli.pptctl as cli_mod
        assert hasattr(cli_mod, "main"), "CLI module must have a main() function"

    def test_all_capabilities_have_cli_commands(self):
        """Every capability command must be implemented by the CLI."""
        from cli.pptctl import CLI_COMMANDS
        for cap in CAPABILITIES:
            if cap.status == CapabilityStatus.removed:
                continue
            assert cap.cli_command, f"Capability {cap.id} has no CLI command"
            assert cap.cli_command in CLI_COMMANDS, (
                f"Capability {cap.id} is not reachable through pptctl {cap.cli_command}"
            )


class TestAgentClientContract:
    """Verify AgentClient methods exist for all capabilities."""

    def test_client_module_imports(self):
        from agent_client.client import AgentClient
        assert AgentClient is not None

    def test_client_has_core_methods(self):
        from agent_client.client import AgentClient
        required_methods = [
            "create_project", "list_projects", "get_project",
            "set_source", "start_pipeline", "get_pipeline_status",
            "resume_pipeline", "list_checkpoints", "approve_checkpoint",
            "get_stage", "regenerate_image", "update_narration",
            "synthesize_tts", "render_video",
            "list_artifacts", "get_artifact",
            "get_meta", "get_diagnostics",
        ]
        for method in required_methods:
            assert hasattr(AgentClient, method), (
                f"AgentClient missing method: {method}"
            )

    def test_polling_module_imports(self):
        from agent_client.polling import poll_operation, PollConfig
        assert poll_operation is not None
        assert PollConfig is not None


class TestOperationsContract:
    """Test the unified operation model."""

    def test_operation_status_enum_values(self):
        from agent_contract.operations import OperationStatus
        expected = {
            "queued", "running", "waiting_for_review",
            "succeeded", "failed", "cancelled", "interrupted",
        }
        actual = {s.value for s in OperationStatus}
        assert actual == expected, f"Missing statuses: {expected - actual}"

    def test_normalize_status_known(self):
        from agent_contract.operations import normalize_status, OperationStatus
        assert normalize_status("running") == OperationStatus.running
        assert normalize_status("idle") == OperationStatus.succeeded
        assert normalize_status("paused") == OperationStatus.waiting_for_review
        assert normalize_status("failed") == OperationStatus.failed

    def test_normalize_status_unknown_defaults_to_running(self):
        from agent_contract.operations import normalize_status, OperationStatus
        assert normalize_status("unknown_xyz") == OperationStatus.running

    def test_checkpoint_stages_complete(self):
        from agent_contract.operations import CHECKPOINT_STAGES
        expected = {
            "storyboard_review", "image_review", "mask_review",
            "narration_review", "audio_review", "video_review",
        }
        assert set(CHECKPOINT_STAGES.keys()) == expected

    def test_operation_from_one_click_basic(self):
        from agent_contract.operations import operation_from_one_click, OperationStatus
        status_dict = {
            "run_id": "test_run_123",
            "status": "running",
            "current_stage": "images",
            "stages": [
                {"name": "preflight", "status": "succeeded"},
                {"name": "storyboard", "status": "succeeded"},
                {"name": "images", "status": "running"},
            ],
            "message": "Generating images...",
        }
        op = operation_from_one_click(status_dict, "proj_abc")
        assert op.operation_id == "test_run_123"
        assert op.project_id == "proj_abc"
        assert op.status == OperationStatus.running
        assert op.progress == 66  # 2/3 completed


class TestArtifactsContract:
    """Test artifact URI building and type system."""

    def test_build_resource_uri_for_image(self):
        from agent_contract.artifacts import build_resource_uri
        uri = build_resource_uri("proj_1", "image", "slide_001")
        assert "proj_1" in uri
        assert "slide_001" in uri

    def test_build_resource_uri_for_video(self):
        from agent_contract.artifacts import build_resource_uri
        uri = build_resource_uri("proj_1", "video")
        assert "proj_1" in uri

    def test_artifact_type_enum(self):
        from agent_contract.artifacts import ArtifactType
        expected = {"image", "audio", "video", "pptx", "contract", "narration", "mask", "subtitle", "other"}
        actual = {t.value for t in ArtifactType}
        assert expected.issubset(actual), f"Missing types: {expected - actual}"
