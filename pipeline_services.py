"""In-process service facade for the production PPT pipeline.

The web routes and local one-click automation share the same source-owned
operations.  This facade deliberately avoids HTTP/TestClient calls while the
large route handlers are gradually decomposed into smaller domain services.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any


class ProjectPipelineServices:
    """Call production pipeline operations directly inside the server process."""

    def __init__(self, server_module: ModuleType, db: Any, project_id: str) -> None:
        self.server = server_module
        self.db = db
        self.project_id = project_id

    def storyboard_script(self) -> dict[str, Any]:
        return self.server.execute_step2_script_plan(self.project_id, {}, self.db)

    def storyboard_visual(self) -> dict[str, Any]:
        return self.server.execute_step2_visual_plan(self.project_id, self.db)

    def storyboard_compose(self) -> dict[str, Any]:
        return self.server.compose_step2_visual_contract(self.project_id, self.db)

    def image_prompts(self) -> dict[str, Any]:
        return self.server.get_slide_prompts(self.project_id, self.db)

    def generate_image(self, slide_id: str, prompt: str) -> dict[str, Any]:
        return self.server.generate_slide_image(
            self.project_id,
            slide_id=slide_id,
            prompt=prompt,
            preview=False,
            db=self.db,
        )

    def confirm_images(self) -> dict[str, Any]:
        return self.server.confirm_images(self.project_id, self.db)

    def annotate_ai_mask(self, payload: dict[str, Any]) -> dict[str, Any]:
        from runtime_ai_mask import annotate_project

        project = self._project()
        settings = payload.get("settings") if isinstance(payload.get("settings"), dict) else {}
        return annotate_project(self.server, project, settings)

    def mask_manifest(self) -> dict[str, Any]:
        return self.server.get_step5_result(self.project_id, self.db)

    def repair_mask_manifest(self) -> dict[str, Any]:
        return self.server.repair_step5_result(self.project_id, self.db)

    def build_mask_assets(self, manifest: dict[str, Any]) -> dict[str, Any]:
        return self.server.update_step5_result(
            self.project_id,
            manifest,
            build_assets=True,
            db=self.db,
        )

    def narration(self) -> dict[str, Any]:
        return self.server.get_step6_result(self.project_id, self.db)

    def repair_narration(self) -> dict[str, Any]:
        return self.server.repair_step6_result(self.project_id, self.db)

    def init_narration(self) -> dict[str, Any]:
        return self.server.init_step6_narration(self.project_id, self.db)

    def annotate_narration(self, beats: dict[str, Any]) -> dict[str, Any]:
        return self.server.annotate_step6_narration(self.project_id, beats, self.db)

    def save_narration(self, beats: dict[str, Any]) -> dict[str, Any]:
        return self.server.update_step6_result(self.project_id, beats, self.db)

    def synthesize_audio(self) -> dict[str, Any]:
        return self.server.synthesize_tts_resumable(self.project_id, self.db)

    def confirm_audio(self) -> dict[str, Any]:
        return self.server.confirm_tts_audio(
            self.project_id,
            {"confirmation_mode": "automatic_technical"},
            self.db,
        )

    def render_video(self) -> dict[str, Any]:
        return self.server.render_video(self.project_id, self.db)

    def _project(self) -> Any:
        project = (
            self.db.query(self.server.Project)
            .filter(self.server.Project.id == self.project_id)
            .first()
        )
        if not project:
            raise self.server.HTTPException(status_code=404, detail="项目不存在")
        return project
