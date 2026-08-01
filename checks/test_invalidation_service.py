import json
from pathlib import Path
import tempfile

import invalidation_service


class FakeProject:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = str(run_dir)
        self.current_step = 8
        self._statuses = {str(step): "completed" for step in range(1, 9)}

    def get_step_status(self):
        return dict(self._statuses)

    def set_step_status(self, statuses):
        self._statuses = dict(statuses)


def seed_common_derivatives(run_dir: Path) -> None:
    (run_dir / "planning").mkdir(parents=True, exist_ok=True)
    (run_dir / "planning" / "audio_confirmed.json").write_text("{}", encoding="utf-8")
    (run_dir / "remotion_props.json").write_text("{}", encoding="utf-8")


def seed_slide_derivatives(run_dir: Path, *slide_ids: str) -> None:
    slides = []
    for slide_id in slide_ids:
        target = run_dir / "slides" / slide_id
        (target / "assets").mkdir(parents=True)
        for filename in (
            "scene.json",
            "animation_timeline.json",
            "reveal_report.json",
            "mask_preview.png",
        ):
            (target / filename).write_bytes(b"derived")
        (target / "assets" / "layer.png").write_bytes(b"layer")
        (target / "visual_draft.png").write_bytes(b"source-image")
        slides.append(
            {
                "slide_id": slide_id,
                "status": "completed",
                "groups": [{"id": f"{slide_id}_group"}],
                "semantic_blocks": [{"id": f"{slide_id}_block"}],
            }
        )
    (run_dir / "reveal_manifest.json").write_text(
        json.dumps({"slides": slides}),
        encoding="utf-8",
    )


def test_upstream_and_empty_storyboard_invalidation_matrix() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        seed_common_derivatives(run_dir)
        project = FakeProject(run_dir)

        report = invalidation_service.upstream_content_changed(project, 1)

        assert report.reason == "article_changed"
        assert project.current_step == 1
        assert project._statuses["1"] == "completed"
        assert all(
            project._statuses[str(step)] == "pending_reconfirmation"
            for step in range(2, 9)
        )
        assert not (run_dir / "planning" / "audio_confirmed.json").exists()
        assert not (run_dir / "remotion_props.json").exists()

        seed_common_derivatives(run_dir)
        project = FakeProject(run_dir)
        report = invalidation_service.empty_storyboard_changed(project)

        assert report.reason == "storyboard_empty"
        assert project.current_step == 2
        assert project._statuses["2"] == "in_progress"
        assert all(
            project._statuses[str(step)] == "pending_reconfirmation"
            for step in range(3, 9)
        )


def test_slide_image_invalidation_is_scoped_and_preserves_sources() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        seed_common_derivatives(run_dir)
        seed_slide_derivatives(run_dir, "slide_001", "slide_002")
        project = FakeProject(run_dir)

        report = invalidation_service.slide_images_changed(
            project,
            ["slide_001"],
            all_images_exist=True,
        )

        manifest = json.loads(
            (run_dir / "reveal_manifest.json").read_text(encoding="utf-8")
        )
        first, second = manifest["slides"]
        assert report.slide_ids == ("slide_001",)
        assert first["groups"] == []
        assert first["semantic_blocks"] == []
        assert first["status"] == "pending"
        assert second["groups"] == [{"id": "slide_002_group"}]
        assert not (run_dir / "slides" / "slide_001" / "scene.json").exists()
        assert not (run_dir / "slides" / "slide_001" / "assets").exists()
        assert (run_dir / "slides" / "slide_001" / "visual_draft.png").exists()
        assert (run_dir / "slides" / "slide_002" / "scene.json").exists()
        assert not (run_dir / "planning" / "audio_confirmed.json").exists()
        assert not (run_dir / "remotion_props.json").exists()
        assert project.current_step == 3
        assert project._statuses["3"] == "completed"
        assert all(
            project._statuses[str(step)] == "pending_reconfirmation"
            for step in range(4, 9)
        )


def test_style_background_and_narration_invalidation_matrix() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        seed_common_derivatives(run_dir)
        seed_slide_derivatives(run_dir, "slide_001", "slide_002")
        project = FakeProject(run_dir)

        subtitle_report = invalidation_service.subtitle_style_changed(project)
        assert subtitle_report.affected_steps == (8,)
        assert project._statuses["8"] == "pending_reconfirmation"
        assert (run_dir / "planning" / "audio_confirmed.json").exists()
        assert not (run_dir / "remotion_props.json").exists()

        (run_dir / "remotion_props.json").write_text("{}", encoding="utf-8")
        project = FakeProject(run_dir)
        background_report = invalidation_service.video_background_changed(
            project,
            ["slide_001", "slide_002"],
        )
        assert background_report.affected_steps == (5, 8)
        assert project.current_step == 3
        assert project._statuses["5"] == "pending_reconfirmation"
        assert project._statuses["8"] == "pending_reconfirmation"
        assert (run_dir / "planning" / "audio_confirmed.json").exists()
        assert not (run_dir / "slides" / "slide_001" / "scene.json").exists()
        assert not (run_dir / "slides" / "slide_002" / "scene.json").exists()

        project = FakeProject(run_dir)
        narration_report = invalidation_service.narration_synthesis_started(project)
        assert narration_report.affected_steps == (7, 8)
        assert project.current_step == 7
        assert project._statuses["7"] == "in_progress"
        assert project._statuses["8"] == "pending_reconfirmation"
        assert not (run_dir / "planning" / "audio_confirmed.json").exists()


def test_stage_completion_uses_same_invalidation_rules() -> None:
    with tempfile.TemporaryDirectory() as value:
        run_dir = Path(value)
        seed_common_derivatives(run_dir)
        project = FakeProject(run_dir)

        report = invalidation_service.complete_stage(project, 6)

        assert report.reason == "stage_completed"
        assert project.current_step == 8
        assert project._statuses["6"] == "completed"
        assert project._statuses["7"] == "pending_reconfirmation"
        assert project._statuses["8"] == "pending_reconfirmation"
        assert not (run_dir / "planning" / "audio_confirmed.json").exists()
        assert not (run_dir / "remotion_props.json").exists()
