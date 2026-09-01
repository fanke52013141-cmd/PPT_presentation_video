"""Deep validation tests for Pydantic models.

Tests field constraints, enum values, defaults, serialization round-trips,
and edge cases that could cause runtime errors.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_contract.models import (
    CanvasProfile,
    AutomationMode,
    ReviewPolicy,
    ProjectCreateRequest,
    ProjectCreateResult,
    ProjectSummary,
    ProjectListRequest,
    ProjectListResult,
    ProjectGetResult,
    ProjectUpdateRequest,
    ProjectUpdateResult,
    SourceSetRequest,
    SourceSetResult,
    PipelineRunRequest,
    PipelineRunResult,
    PipelineStatusResult,
    PipelineResumeRequest,
    StageGetResult,
    NarrationUpdateRequest,
    ImageRegenerateRequest,
    ImageRegenerateResult,
    TtsSynthesizeRequest,
    TtsSynthesizeResult,
    VideoRenderRequest,
    VideoRenderResult,
    CheckpointApproveRequest,
    CheckpointResult,
    ArtifactsListRequest,
    ArtifactsListResult,
    ArtifactGetResult,
    ArtifactInfo,
    DiagnosticsResult,
)


class TestEnumValues:
    """Verify all enums have the expected values."""

    def test_canvas_profile_values(self):
        assert CanvasProfile.landscape_16_9.value == "landscape_16_9"
        assert CanvasProfile.portrait_9_16.value == "portrait_9_16"
        assert len(list(CanvasProfile)) == 2

    def test_automation_mode_values(self):
        assert AutomationMode.auto.value == "auto"
        assert AutomationMode.manual.value == "manual"
        assert AutomationMode.agent.value == "agent"
        assert len(list(AutomationMode)) == 3

    def test_review_policy_values(self):
        assert ReviewPolicy.none.value == "none"
        assert ReviewPolicy.images_and_video.value == "images_and_video"
        assert ReviewPolicy.all_stages.value == "all_stages"
        assert len(list(ReviewPolicy)) == 3


class TestProjectCreateRequest:
    """Test ProjectCreateRequest field validation."""

    def test_valid_minimal(self):
        req = ProjectCreateRequest(name="Test")
        assert req.name == "Test"
        assert req.description == ""
        assert req.canvas_profile == CanvasProfile.landscape_16_9
        assert req.automation_mode == AutomationMode.auto
        assert req.review_policy == ReviewPolicy.none
        assert req.idempotency_key is None

    def test_valid_full(self):
        req = ProjectCreateRequest(
            name="Full Project",
            description="A detailed description",
            canvas_profile=CanvasProfile.portrait_9_16,
            automation_mode=AutomationMode.agent,
            review_policy=ReviewPolicy.all_stages,
            idempotency_key="key-123",
        )
        assert req.canvas_profile == CanvasProfile.portrait_9_16

    def test_empty_name_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreateRequest(name="")

    def test_name_too_long_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreateRequest(name="x" * 201)

    def test_description_too_long_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreateRequest(name="ok", description="x" * 2001)

    def test_invalid_canvas_profile_rejected(self):
        with pytest.raises(ValidationError):
            ProjectCreateRequest(name="ok", canvas_profile="square")

    def test_string_enum_coercion(self):
        """Pydantic should coerce string values to enum."""
        req = ProjectCreateRequest(name="ok", canvas_profile="portrait_9_16")
        assert req.canvas_profile == CanvasProfile.portrait_9_16

    def test_serialization_roundtrip(self):
        req = ProjectCreateRequest(name="Roundtrip", description="test")
        data = req.model_dump()
        restored = ProjectCreateRequest(**data)
        assert restored.name == req.name
        assert restored.description == req.description


class TestProjectSummary:
    """Test ProjectSummary model."""

    def test_valid_creation(self):
        summary = ProjectSummary(
            project_id="proj_123",
            name="Test",
            description="desc",
            canvas_profile="landscape_16_9",
            ai_mode="auto",
            current_step=1,
            status="active",
        )
        assert summary.project_id == "proj_123"
        assert summary.step_status == {}  # default
        assert summary.revision == 0  # default

    def test_with_step_status(self):
        summary = ProjectSummary(
            project_id="p1",
            name="t",
            description="",
            canvas_profile="landscape_16_9",
            ai_mode="auto",
            current_step=3,
            status="active",
            step_status={"step1": "completed", "step2": "pending"},
        )
        assert summary.step_status["step1"] == "completed"

    def test_with_revision(self):
        summary = ProjectSummary(
            project_id="p1",
            name="t",
            description="",
            canvas_profile="landscape_16_9",
            ai_mode="auto",
            current_step=3,
            status="active",
            revision=42,
        )
        assert summary.revision == 42

    def test_revision_in_serialization(self):
        summary = ProjectSummary(
            project_id="p1", name="t", description="",
            canvas_profile="landscape_16_9", ai_mode="auto",
            current_step=1, status="active", revision=7,
        )
        d = summary.model_dump(mode="json")
        assert "revision" in d
        assert d["revision"] == 7

    def test_missing_required_field_rejected(self):
        with pytest.raises(ValidationError):
            ProjectSummary(name="no id")


class TestProjectListRequest:
    def test_defaults(self):
        req = ProjectListRequest()
        assert req.status_filter is None
        assert req.limit == 50

    def test_limit_boundary_values(self):
        ProjectListRequest(limit=1)
        ProjectListRequest(limit=200)

    def test_limit_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            ProjectListRequest(limit=0)

    def test_limit_above_maximum_rejected(self):
        with pytest.raises(ValidationError):
            ProjectListRequest(limit=201)


class TestSourceSetRequest:
    def test_both_none_accepted(self):
        """Both content and topic can be None at model level (validation happens in route)."""
        req = SourceSetRequest()
        assert req.content is None
        assert req.topic is None

    def test_with_content(self):
        req = SourceSetRequest(content="# Hello\nWorld")
        assert req.content == "# Hello\nWorld"

    def test_with_topic(self):
        req = SourceSetRequest(topic="AI的未来")
        assert req.topic == "AI的未来"


class TestPipelineRunRequest:
    def test_defaults(self):
        req = PipelineRunRequest()
        assert req.start_from == "preflight"
        assert req.stop_at is None
        assert req.mode == "resume"

    def test_with_stop_at(self):
        req = PipelineRunRequest(stop_at="image_review")
        assert req.stop_at == "image_review"


class TestCheckpointApproveRequest:
    def test_defaults(self):
        req = CheckpointApproveRequest(checkpoint="image_review")
        assert req.checkpoint == "image_review"
        assert req.approved is True
        assert req.notes == ""

    def test_rejection(self):
        req = CheckpointApproveRequest(checkpoint="image_review", approved=False, notes="bad quality")
        assert req.approved is False
        assert req.notes == "bad quality"


class TestImageRegenerateRequest:
    def test_valid(self):
        req = ImageRegenerateRequest(slide_id="slide_001", instruction="更亮一些")
        assert req.slide_id == "slide_001"
        assert req.instruction == "更亮一些"

    def test_defaults(self):
        req = ImageRegenerateRequest(slide_id="s1")
        assert req.instruction == ""
        assert req.idempotency_key is None


class TestNarrationUpdateRequest:
    def test_valid(self):
        req = NarrationUpdateRequest(slide_id="s1", narration_text="Hello world")
        assert req.narration_text == "Hello world"

    def test_expected_revision_defaults_none(self):
        req = NarrationUpdateRequest(slide_id="s1", narration_text="test")
        assert req.expected_revision is None

    def test_with_expected_revision(self):
        req = NarrationUpdateRequest(
            slide_id="s1", narration_text="test", expected_revision=3,
        )
        assert req.expected_revision == 3


class TestOptimisticLockFields:
    """Verify expected_revision is accepted on all update models."""

    def test_project_update_expected_revision_none_default(self):
        req = ProjectUpdateRequest()
        assert req.expected_revision is None

    def test_project_update_with_expected_revision(self):
        req = ProjectUpdateRequest(description="updated", expected_revision=5)
        assert req.expected_revision == 5


class TestTtsSynthesizeRequest:
    def test_defaults(self):
        req = TtsSynthesizeRequest()
        assert req.slide_ids is None

    def test_with_slide_ids(self):
        req = TtsSynthesizeRequest(slide_ids=["slide_001", "slide_002"])
        assert len(req.slide_ids) == 2


class TestArtifactModels:
    def test_artifact_info_defaults(self):
        info = ArtifactInfo(
            artifact_id="art_1",
            artifact_type="image",
            filename="test.png",
            mime_type="image/png",
        )
        assert info.size_bytes == 0
        assert info.resource_uri == ""
        assert info.slide_id is None
        assert info.revision == 0

    def test_artifact_info_to_dict(self):
        info = ArtifactInfo(
            artifact_id="art_1",
            artifact_type="video",
            filename="out.mp4",
            mime_type="video/mp4",
            size_bytes=1024,
        )
        d = info.model_dump()
        assert d["artifact_id"] == "art_1"
        assert d["size_bytes"] == 1024


class TestDiagnosticsResult:
    def test_defaults(self):
        diag = DiagnosticsResult(
            agent_api_version="1.0.0",
            contract_hash="abc123",
        )
        assert diag.application_version == ""
        assert diag.capabilities == []
        assert diag.checks == {}


class TestJsonSchemaGeneration:
    """Verify all concrete models can generate JSON schemas (for MCP/OpenAPI)."""

    def test_all_concrete_models_generate_schema(self):
        from pydantic import BaseModel
        concrete_models = [
            ProjectCreateRequest, ProjectCreateResult, ProjectSummary,
            ProjectListRequest, ProjectListResult, ProjectGetResult,
            ProjectUpdateRequest, ProjectUpdateResult,
            SourceSetRequest, SourceSetResult,
            PipelineRunRequest, PipelineRunResult, PipelineStatusResult,
            PipelineResumeRequest,
            StageGetResult, NarrationUpdateRequest,
            ImageRegenerateRequest, ImageRegenerateResult,
            TtsSynthesizeRequest, TtsSynthesizeResult,
            VideoRenderRequest, VideoRenderResult,
            CheckpointApproveRequest, CheckpointResult,
            ArtifactsListRequest, ArtifactsListResult, ArtifactGetResult,
            ArtifactInfo,
            DiagnosticsResult,
        ]
        for model in concrete_models:
            schema = model.model_json_schema()
            assert isinstance(schema, dict)
            assert "properties" in schema, f"{model.__name__} schema has no properties"
