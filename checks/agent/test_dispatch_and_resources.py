"""Tests for MCP tools._dispatch routing and _format_result formatting.

Verifies that every capability ID routes to the correct AgentClient method
with the correct arguments.
"""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock

from agent_client.client import AgentClient, AgentClientError
from mcp_server import tools, presenters


class TestDispatchRouting:
    """Verify _dispatch routes to correct client methods."""

    @pytest.fixture
    def mock_client(self):
        client = MagicMock(spec=AgentClient)
        client.create_project.return_value = {"project": {"project_id": "p1"}}
        client.list_projects.return_value = {"projects": [], "total": 0}
        client.get_project.return_value = {"project": {}}
        client.update_project.return_value = {"project": {}, "updated": True}
        client.set_source.return_value = {"article_imported": True}
        client.start_pipeline.return_value = {"operation_id": "op1"}
        client.get_pipeline_status.return_value = {"status": "running"}
        client.resume_pipeline.return_value = {"operation_id": "op2"}
        client.approve_checkpoint.return_value = {"approved": True}
        client.get_stage.return_value = {"stage": "storyboard"}
        client.regenerate_image.return_value = {"slide_id": "s1"}
        client.update_narration.return_value = {"updated": True}
        client.synthesize_tts.return_value = {"job_id": "j1"}
        client.render_video.return_value = {"job_id": "j2"}
        client.list_artifacts.return_value = {"artifacts": [], "total": 0}
        client.get_artifact.return_value = {"artifact": {}}
        client.get_diagnostics.return_value = {"agent_api_version": "1.0.0"}
        client.get_meta.return_value = {"agent_api_version": "1.0.0"}
        return client

    def test_dispatch_project_create(self, mock_client):
        tools._dispatch("project.create", {"name": "Test", "description": "d"}, mock_client)
        mock_client.create_project.assert_called_once()

    def test_dispatch_project_list(self, mock_client):
        tools._dispatch("project.list", {"limit": 10}, mock_client)
        mock_client.list_projects.assert_called_once()

    def test_dispatch_project_get(self, mock_client):
        tools._dispatch("project.get", {"project_id": "p1"}, mock_client)
        mock_client.get_project.assert_called_once_with("p1")

    def test_dispatch_project_update(self, mock_client):
        tools._dispatch("project.update", {"project_id": "p1", "name": "New"}, mock_client)
        mock_client.update_project.assert_called_once()

    def test_dispatch_source_set(self, mock_client):
        tools._dispatch("source.set", {"project_id": "p1", "content": "hello"}, mock_client)
        mock_client.set_source.assert_called_once()

    def test_dispatch_pipeline_run(self, mock_client):
        tools._dispatch("pipeline.run", {"project_id": "p1", "stop_at": "image_review"}, mock_client)
        mock_client.start_pipeline.assert_called_once()

    def test_dispatch_pipeline_status(self, mock_client):
        tools._dispatch("pipeline.status", {"project_id": "p1"}, mock_client)
        mock_client.get_pipeline_status.assert_called_once_with("p1")

    def test_dispatch_pipeline_resume(self, mock_client):
        tools._dispatch("pipeline.resume", {"project_id": "p1"}, mock_client)
        mock_client.resume_pipeline.assert_called_once()

    def test_dispatch_checkpoint_approve(self, mock_client):
        tools._dispatch("checkpoint.approve", {
            "project_id": "p1", "checkpoint": "image_review", "approved": True
        }, mock_client)
        mock_client.approve_checkpoint.assert_called_once()

    def test_dispatch_stage_get(self, mock_client):
        tools._dispatch("stage.get", {"project_id": "p1", "stage": "narration"}, mock_client)
        mock_client.get_stage.assert_called_once_with("p1", "narration")

    def test_dispatch_image_regenerate(self, mock_client):
        tools._dispatch("image.regenerate", {
            "project_id": "p1", "slide_id": "s1", "instruction": "brighter"
        }, mock_client)
        mock_client.regenerate_image.assert_called_once()

    def test_dispatch_narration_update(self, mock_client):
        tools._dispatch("narration.update", {
            "project_id": "p1", "slide_id": "s1", "narration_text": "hello"
        }, mock_client)
        mock_client.update_narration.assert_called_once()

    def test_dispatch_tts_synthesize(self, mock_client):
        tools._dispatch("tts.synthesize", {"project_id": "p1"}, mock_client)
        mock_client.synthesize_tts.assert_called_once()

    def test_dispatch_video_render(self, mock_client):
        tools._dispatch("video.render", {"project_id": "p1"}, mock_client)
        mock_client.render_video.assert_called_once()

    def test_dispatch_artifacts_list(self, mock_client):
        tools._dispatch("artifacts.list", {"project_id": "p1"}, mock_client)
        mock_client.list_artifacts.assert_called_once()

    def test_dispatch_artifact_get(self, mock_client):
        tools._dispatch("artifact.get", {"project_id": "p1", "artifact_id": "a1"}, mock_client)
        mock_client.get_artifact.assert_called_once_with("p1", "a1")

    def test_dispatch_diagnostics(self, mock_client):
        tools._dispatch("diagnostics", {}, mock_client)
        mock_client.get_diagnostics.assert_called_once()

    def test_dispatch_unknown_raises(self, mock_client):
        with pytest.raises(ValueError, match="Unknown capability"):
            tools._dispatch("nonexistent.cap", {}, mock_client)


class TestFormatResult:
    """Verify _format_result produces MCP content blocks."""

    def test_format_project_create(self):
        result = {"project": {"name": "Test", "project_id": "p1"}}
        blocks = tools._format_result("project.create", result)
        assert len(blocks) >= 1
        assert blocks[0]["type"] == "text"
        assert "Test" in blocks[0]["text"]

    def test_format_project_list(self):
        result = {"projects": [{"name": "A"}, {"name": "B"}], "total": 2}
        blocks = tools._format_result("project.list", result)
        assert len(blocks) == 2  # one block per project

    def test_format_pipeline_status(self):
        result = {"operation_id": "op1", "status": "running", "progress": 50}
        blocks = tools._format_result("pipeline.status", result)
        assert len(blocks) == 1
        assert "running" in blocks[0]["text"]

    def test_format_artifacts_list(self):
        result = {"project_id": "p1", "artifacts": [{"artifact_type": "image", "filename": "f.png"}], "total": 1}
        blocks = tools._format_result("artifacts.list", result)
        assert len(blocks) == 1

    def test_format_diagnostics(self):
        result = {"agent_api_version": "1.0.0", "checks": {"db": "ok"}}
        blocks = tools._format_result("diagnostics", result)
        assert len(blocks) == 1
        assert "1.0.0" in blocks[0]["text"]

    def test_format_default_json(self):
        """Unknown capability IDs should produce a JSON text block."""
        result = {"custom": "data"}
        blocks = tools._format_result("unknown.cap", result)
        assert len(blocks) == 1
        parsed = json.loads(blocks[0]["text"])
        assert parsed["custom"] == "data"


class TestToolHandlerFactory:
    """Test the handler factory wraps dispatch correctly."""

    def test_handler_success(self):
        mock_client = MagicMock(spec=AgentClient)
        mock_client.list_projects.return_value = {"projects": [], "total": 0}

        handler = tools._make_tool_handler(
            next(c for c in tools.CAPABILITIES if c.id == "project.list")
        )
        blocks = handler({"limit": 5}, mock_client)
        assert isinstance(blocks, list)
        mock_client.list_projects.assert_called_once()

    def test_handler_catches_client_error(self):
        mock_client = MagicMock(spec=AgentClient)
        mock_client.get_project.side_effect = AgentClientError("Not found", status_code=404)

        handler = tools._make_tool_handler(
            next(c for c in tools.CAPABILITIES if c.id == "project.get")
        )
        blocks = handler({"project_id": "xxx"}, mock_client)
        assert len(blocks) == 1
        assert "API Error" in blocks[0]["text"]

    def test_handler_catches_generic_error(self):
        mock_client = MagicMock(spec=AgentClient)
        mock_client.get_project.side_effect = RuntimeError("Unexpected")

        handler = tools._make_tool_handler(
            next(c for c in tools.CAPABILITIES if c.id == "project.get")
        )
        blocks = handler({"project_id": "xxx"}, mock_client)
        assert len(blocks) == 1
        assert "Tool execution failed" in blocks[0]["text"]


class TestResourceUriParsing:
    """Test resource URI parsing in mcp_server.resources."""

    def test_parse_summary_uri(self):
        from mcp_server.resources import parse_resource_uri
        result = parse_resource_uri("ppt://projects/p1/summary")
        assert result is not None
        assert result[0] == "p1"
        assert result[1] == "summary"

    def test_parse_slides_uri(self):
        from mcp_server.resources import parse_resource_uri
        result = parse_resource_uri("ppt://projects/p1/slides")
        assert result is not None
        assert result[1] == "slides"

    def test_parse_slide_image_uri(self):
        from mcp_server.resources import parse_resource_uri
        result = parse_resource_uri("ppt://projects/p1/slides/s01/image")
        assert result is not None
        assert result[1] == "slide_image"
        assert result[2]["slide_id"] == "s01"

    def test_parse_slide_audio_uri(self):
        from mcp_server.resources import parse_resource_uri
        result = parse_resource_uri("ppt://projects/p1/slides/s01/audio")
        assert result is not None
        assert result[1] == "slide_audio"

    def test_parse_video_uri(self):
        from mcp_server.resources import parse_resource_uri
        result = parse_resource_uri("ppt://projects/p1/videos/latest")
        assert result is not None
        assert result[1] == "video_latest"

    def test_parse_contract_uri(self):
        from mcp_server.resources import parse_resource_uri
        result = parse_resource_uri("ppt://projects/p1/contract")
        assert result is not None
        assert result[1] == "contract"

    def test_parse_invalid_uri(self):
        from mcp_server.resources import parse_resource_uri
        assert parse_resource_uri("http://example.com") is None
        assert parse_resource_uri("ppt://unknown") is None
        assert parse_resource_uri("") is None


class TestOperationsDeep:
    """Deep tests for operations.py edge cases."""

    def test_normalize_status_all_mapped(self):
        from agent_contract.operations import normalize_status, OperationStatus
        test_cases = [
            ("idle", OperationStatus.succeeded),
            ("running", OperationStatus.running),
            ("paused", OperationStatus.waiting_for_review),
            ("succeeded", OperationStatus.succeeded),
            ("completed", OperationStatus.succeeded),
            ("failed", OperationStatus.failed),
            ("interrupted", OperationStatus.interrupted),
            ("cancelled", OperationStatus.cancelled),
            ("100", OperationStatus.succeeded),
            ("done", OperationStatus.succeeded),
            ("ok", OperationStatus.succeeded),
            ("error", OperationStatus.failed),
            ("0", OperationStatus.failed),
        ]
        for raw, expected in test_cases:
            assert normalize_status(raw) == expected, f"normalize_status('{raw}') should be {expected.value}"

    def test_normalize_status_empty_string(self):
        from agent_contract.operations import normalize_status, OperationStatus
        # Empty string is not in map, defaults to running
        assert normalize_status("") == OperationStatus.running

    def test_get_checkpoint_valid(self):
        from agent_contract.operations import get_checkpoint, CHECKPOINT_STAGES
        for name in CHECKPOINT_STAGES:
            info = get_checkpoint(name)
            assert "label" in info
            assert "internal_stage" in info
            assert "description" in info

    def test_get_checkpoint_invalid(self):
        from agent_contract.operations import get_checkpoint
        with pytest.raises(ValueError, match="Unknown checkpoint"):
            get_checkpoint("nonexistent_checkpoint")

    def test_operation_from_one_click_empty_stages(self):
        from agent_contract.operations import operation_from_one_click, OperationStatus
        op = operation_from_one_click({"status": "idle"}, "p1")
        assert op.status == OperationStatus.succeeded
        assert op.progress == 0

    def test_operation_from_one_click_with_errors(self):
        from agent_contract.operations import operation_from_one_click
        op = operation_from_one_click({
            "status": "failed",
            "stages": [
                {"name": "preflight", "status": "succeeded"},
                {"name": "images", "status": "failed", "blocking_errors": ["GPU OOM"]},
            ],
        }, "p1")
        assert len(op.blocking_errors) == 1
        assert "GPU OOM" in op.blocking_errors[0]

    def test_operation_from_one_click_with_warnings(self):
        from agent_contract.operations import operation_from_one_click
        op = operation_from_one_click({
            "status": "running",
            "stages": [
                {"name": "preflight", "status": "succeeded", "warnings": ["deprecated API"]},
            ],
        }, "p1")
        assert len(op.warnings) == 1

    def test_operation_from_one_click_missing_run_id(self):
        from agent_contract.operations import operation_from_one_click
        op = operation_from_one_click({"status": "running"}, "p1")
        assert op.operation_id == "unknown"


class TestArtifactsDeep:
    """Deep tests for artifacts.py."""

    def test_build_resource_uri_image_with_slide(self):
        from agent_contract.artifacts import build_resource_uri
        uri = build_resource_uri("p1", "image", "slide_001")
        assert uri == "ppt://projects/p1/slides/slide_001/image"

    def test_build_resource_uri_audio_with_slide(self):
        from agent_contract.artifacts import build_resource_uri
        uri = build_resource_uri("p1", "audio", "slide_001")
        assert uri == "ppt://projects/p1/slides/slide_001/audio"

    def test_build_resource_uri_narration_with_slide(self):
        from agent_contract.artifacts import build_resource_uri
        uri = build_resource_uri("p1", "narration", "slide_001")
        assert uri == "ppt://projects/p1/slides/slide_001/narration"

    def test_build_resource_uri_video_no_slide(self):
        from agent_contract.artifacts import build_resource_uri
        uri = build_resource_uri("p1", "video")
        assert uri == "ppt://projects/p1/videos/latest"

    def test_build_resource_uri_pptx_no_slide(self):
        from agent_contract.artifacts import build_resource_uri
        uri = build_resource_uri("p1", "pptx")
        assert uri == "ppt://projects/p1/pptx/latest"

    def test_build_resource_uri_contract_no_slide(self):
        from agent_contract.artifacts import build_resource_uri
        uri = build_resource_uri("p1", "contract")
        assert uri == "ppt://projects/p1/contract"

    def test_build_resource_uri_unknown_type_fallback(self):
        from agent_contract.artifacts import build_resource_uri
        uri = build_resource_uri("p1", "unknown_type")
        assert "unknown_type" in uri
        assert uri.startswith("ppt://")

    def test_mime_for_all_types(self):
        from agent_contract.artifacts import mime_for_type, ArtifactType
        expected_mime = {
            "image": "image/png",
            "audio": "audio/mpeg",
            "video": "video/mp4",
            "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "contract": "application/json",
            "narration": "application/json",
            "mask": "application/json",
            "subtitle": "application/x-subrip",
            "other": "application/octet-stream",
        }
        for type_str, expected in expected_mime.items():
            assert mime_for_type(type_str) == expected, f"MIME mismatch for {type_str}"

    def test_mime_for_invalid_type(self):
        from agent_contract.artifacts import mime_for_type
        assert mime_for_type("nonexistent") == "application/octet-stream"

    def test_artifact_collection_filter(self):
        from agent_contract.artifacts import ArtifactInfo, ArtifactCollection
        artifacts = [
            ArtifactInfo(artifact_id="1", artifact_type="image", filename="a.png", mime_type="image/png"),
            ArtifactInfo(artifact_id="2", artifact_type="video", filename="b.mp4", mime_type="video/mp4"),
            ArtifactInfo(artifact_id="3", artifact_type="image", filename="c.png", mime_type="image/png"),
        ]
        collection = ArtifactCollection(project_id="p1", artifacts=artifacts, total=3)
        images = collection.filter_by_type("image")
        assert len(images) == 2


class TestPresentersDeep:
    """Deep tests for presenter formatting."""

    def test_present_artifact_as_text(self):
        from mcp_server.presenters import present_artifact_as_text
        result = present_artifact_as_text({
            "artifact_id": "art_1",
            "artifact_type": "image",
            "filename": "test.png",
            "mime_type": "image/png",
            "size_bytes": 1024,
            "resource_uri": "ppt://projects/p1/slides/s1/image",
            "slide_id": "s1",
            "revision": 2,
        })
        assert result["type"] == "text"
        text = result["text"]
        assert "art_1" in text
        assert "image" in text
        assert "test.png" in text
        assert "1024 bytes" in text
        assert "s1" in text
        assert "revision: 2" in text.lower() or "Revision: 2" in text

    def test_present_artifact_with_download_url(self):
        from mcp_server.presenters import present_artifact_as_text
        result = present_artifact_as_text({
            "artifact_id": "a1",
            "artifact_type": "video",
            "filename": "out.mp4",
            "mime_type": "video/mp4",
            "download_url": "/api/download/a1",
        })
        assert "/api/download/a1" in result["text"]

    def test_present_artifact_list_empty(self):
        from mcp_server.presenters import present_artifact_list_as_text
        result = present_artifact_list_as_text("p1", [])
        assert "0 items" in result["text"]

    def test_present_operation_status(self):
        from mcp_server.presenters import present_operation_status
        result = present_operation_status({
            "operation_id": "op_123",
            "status": "running",
            "progress": 45,
            "stage": "images",
            "message": "Generating...",
        })
        text = result["text"]
        assert "op_123" in text
        assert "running" in text
        assert "45%" in text
        assert "images" in text

    def test_present_project_summary(self):
        from mcp_server.presenters import present_project_summary
        result = present_project_summary({
            "name": "My Project",
            "project_id": "p1",
            "canvas_profile": "landscape_16_9",
            "ai_mode": "auto",
            "description": "A test",
            "current_step": 3,
        })
        text = result["text"]
        assert "My Project" in text
        assert "p1" in text
        assert "landscape_16_9" in text

    def test_present_contact_sheet(self):
        from mcp_server.presenters import present_contact_sheet
        result = present_contact_sheet("p1", [
            {"slide_id": "s1", "has_image": True, "has_narration": False},
            {"slide_id": "s2", "has_image": False, "has_narration": True},
        ])
        text = result["text"]
        assert "s1" in text
        assert "s2" in text
        assert "|" in text  # table format

    def test_present_image_for_agent_text_only(self):
        from mcp_server.presenters import present_image_for_agent
        artifact = {"artifact_id": "a1", "artifact_type": "image", "filename": "f.png"}
        blocks = present_image_for_agent(artifact, image_base64=None)
        assert len(blocks) == 1
        assert blocks[0]["type"] == "text"

    def test_present_image_for_agent_with_base64(self):
        from mcp_server.presenters import present_image_for_agent
        artifact = {"artifact_id": "a1", "artifact_type": "image", "filename": "f.png", "mime_type": "image/png"}
        blocks = present_image_for_agent(artifact, image_base64="iVBOR...")
        assert len(blocks) == 2
        assert blocks[1]["type"] == "image"
        assert blocks[1]["data"] == "iVBOR..."


class TestCLIParserStructure:
    """Test CLI argument parser structure without executing commands."""

    def test_parser_has_project_subcommands(self):
        from cli.pptctl import build_parser
        parser = build_parser()
        # Find the project subparser
        actions = parser._subparsers._group_actions[0]
        project_parser = None
        for choice_name, choice_parser in actions.choices.items():
            if choice_name == "project":
                project_parser = choice_parser
                break
        assert project_parser is not None
        # Check subcommands exist
        sub_actions = project_parser._subparsers._group_actions[0]
        sub_names = set(sub_actions.choices.keys())
        assert "create" in sub_names
        assert "list" in sub_names
        assert "show" in sub_names
        assert "update" in sub_names

    def test_parser_has_all_top_level_commands(self):
        from cli.pptctl import build_parser
        parser = build_parser()
        actions = parser._subparsers._group_actions[0]
        top_commands = set(actions.choices.keys())
        expected = {"project", "source", "run", "approve", "stage", "image",
                    "narration", "tts", "video", "artifacts", "diagnostics", "meta"}
        assert expected.issubset(top_commands), f"Missing commands: {expected - top_commands}"

    def test_parser_accepts_base_url_override(self):
        from cli.pptctl import build_parser
        parser = build_parser()
        args = parser.parse_args(["--base-url", "http://custom:9999", "meta"])
        assert args.base_url == "http://custom:9999"

    def test_parser_create_requires_name(self):
        """project create should require --name."""
        from cli.pptctl import build_parser
        parser = build_parser()
        # Should not raise — name is provided
        args = parser.parse_args(["project", "create", "--name", "Test"])
        assert args.name == "Test"

    def test_parser_approve_has_reject_flag(self):
        from cli.pptctl import build_parser
        parser = build_parser()
        args = parser.parse_args(["approve", "--project", "p1", "--checkpoint", "image_review", "--reject"])
        assert args.reject is True
