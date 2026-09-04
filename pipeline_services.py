"""In-process service facade for the production PPT pipeline.

The web routes and local one-click automation share the same source-owned
operations.  This facade deliberately avoids HTTP/TestClient calls while the
large route handlers are gradually decomposed into smaller domain services.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import HTTPException

from database import Project


PipelineOperation = Callable[..., dict[str, Any]]
PipelineServiceFactory = Callable[[Any, str], "ProjectPipelineServices"]


_SERVICE_FACTORY: Optional[PipelineServiceFactory] = None


def configure_pipeline_service_factory(factory: PipelineServiceFactory) -> None:
    """Configure the application-owned factory for pipeline service facades.

    The composition root is the only place that knows how the production
    pipeline operations are wired.  Secondary interfaces such as Agent API
    must retrieve the same facade through this function instead of inventing
    an alternative dependency graph.
    """
    global _SERVICE_FACTORY
    _SERVICE_FACTORY = factory


def get_project_pipeline_services(db: Any, project_id: str) -> "ProjectPipelineServices":
    """Return the production pipeline facade for one project."""
    if _SERVICE_FACTORY is None:
        raise RuntimeError("Pipeline service factory has not been configured")
    return _SERVICE_FACTORY(db, project_id)


@dataclass(frozen=True)
class StoryboardPipelineOperations:
    script_plan: PipelineOperation
    visual_plan: PipelineOperation
    compose_contract: PipelineOperation


@dataclass(frozen=True)
class ImagePipelineOperations:
    slide_prompts: PipelineOperation
    generate_slide_image: PipelineOperation
    confirm_images: PipelineOperation


@dataclass(frozen=True)
class MaskPipelineOperations:
    get_result: PipelineOperation
    repair_result: PipelineOperation
    update_result: PipelineOperation


@dataclass(frozen=True)
class NarrationPipelineOperations:
    get_result: PipelineOperation
    repair_result: PipelineOperation
    initialize: PipelineOperation
    annotate: PipelineOperation
    update_result: PipelineOperation


@dataclass(frozen=True)
class MediaPipelineOperations:
    synthesize_audio: PipelineOperation
    confirm_audio: PipelineOperation
    render_video: PipelineOperation
    render_video_status: PipelineOperation


@dataclass(frozen=True)
class PipelineOperations:
    storyboard: StoryboardPipelineOperations
    images: ImagePipelineOperations
    mask: MaskPipelineOperations
    narration: NarrationPipelineOperations
    media: MediaPipelineOperations


class ProjectPipelineServices:
    """Call production pipeline operations directly inside the server process."""

    def __init__(
        self,
        operations: PipelineOperations,
        db: Any,
        project_id: str,
    ) -> None:
        self.operations = operations
        self.db = db
        self.project_id = project_id

    def storyboard_script(self) -> dict[str, Any]:
        return self.operations.storyboard.script_plan(self.project_id, self.db, {})

    def storyboard_visual(self) -> dict[str, Any]:
        return self.operations.storyboard.visual_plan(self.project_id, self.db)

    def storyboard_compose(self) -> dict[str, Any]:
        return self.operations.storyboard.compose_contract(self.project_id, self.db)

    def image_prompts(self) -> dict[str, Any]:
        return self.operations.images.slide_prompts(self.project_id, self.db)

    def generate_image(self, slide_id: str, prompt: str) -> dict[str, Any]:
        return self.operations.images.generate_slide_image(
            self.project_id,
            slide_id=slide_id,
            prompt=prompt,
            preview=False,
            db=self.db,
        )

    def confirm_images(self) -> dict[str, Any]:
        return self.operations.images.confirm_images(self.project_id, self.db)

    def annotate_ai_mask(self, payload: dict[str, Any]) -> dict[str, Any]:
        from ai_mask_service import get_ai_mask_task_service

        project = self._project()
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        slide_ids = payload.get("slide_ids") if isinstance(payload.get("slide_ids"), list) else None
        return get_ai_mask_task_service().annotate_project(project, settings, slide_ids)

    def mask_manifest(self) -> dict[str, Any]:
        return self.operations.mask.get_result(self._project())

    def repair_mask_manifest(self) -> dict[str, Any]:
        return self.operations.mask.repair_result(self._project())

    def build_mask_assets(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return self.operations.mask.update_result(
            self._project(),
            manifest,
            build_assets=True,
            db=self.db,
        )

    def narration(self) -> dict[str, Any]:
        return self.operations.narration.get_result(self.project_id, self.db)

    def repair_narration(self) -> dict[str, Any]:
        return self.operations.narration.repair_result(self.project_id, self.db)

    def init_narration(self) -> dict[str, Any]:
        return self.operations.narration.initialize(self.project_id, self.db)

    def annotate_narration(self, beats: dict[str, Any]) -> dict[str, Any]:
        return self.operations.narration.annotate(
            self.project_id,
            self.db,
            beats,
        )

    def save_narration(self, beats: dict[str, Any]) -> dict[str, Any]:
        return self.operations.narration.update_result(
            self.project_id,
            beats,
            self.db,
        )

    def synthesize_audio(self) -> dict[str, Any]:
        return self.operations.media.synthesize_audio(self.project_id, self.db)

    def confirm_audio(self) -> dict[str, Any]:
        return self.operations.media.confirm_audio(
            self.project_id,
            self.db,
            {"confirmation_mode": "automatic_technical"},
        )

    def render_video(self) -> dict[str, Any]:
        return self.operations.media.render_video(self.project_id, self.db)

    def render_video_status(self, task_id: str | None = None) -> dict[str, Any]:
        return self.operations.media.render_video_status(
            self.project_id,
            self.db,
            task_id=task_id,
        )

    def _project(self) -> Project:
        project = (
            self.db.query(Project)
            .filter(Project.id == self.project_id)
            .first()
        )
        if not project:
            raise HTTPException(status_code=404, detail="项目不存在")
        return project
