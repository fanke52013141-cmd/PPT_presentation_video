from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline_services import (
    ImagePipelineOperations,
    MaskPipelineOperations,
    MediaPipelineOperations,
    NarrationPipelineOperations,
    PipelineOperations,
    ProjectPipelineServices,
    StoryboardPipelineOperations,
)


def _recording_operation(name: str, calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]]):
    def operation(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append((name, args, kwargs))
        return {"operation": name}

    return operation


def test_pipeline_facade_dispatches_through_explicit_operation_groups() -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    operation = lambda name: _recording_operation(name, calls)
    operations = PipelineOperations(
        storyboard=StoryboardPipelineOperations(
            script_plan=operation("storyboard_script"),
            visual_plan=operation("storyboard_visual"),
            compose_contract=operation("storyboard_compose"),
        ),
        images=ImagePipelineOperations(
            slide_prompts=operation("image_prompts"),
            generate_slide_image=operation("generate_image"),
            confirm_images=operation("confirm_images"),
        ),
        mask=MaskPipelineOperations(
            get_result=operation("mask_manifest"),
            repair_result=operation("repair_mask_manifest"),
            update_result=operation("build_mask_assets"),
        ),
        narration=NarrationPipelineOperations(
            get_result=operation("narration"),
            repair_result=operation("repair_narration"),
            initialize=operation("init_narration"),
            annotate=operation("annotate_narration"),
            update_result=operation("save_narration"),
        ),
        media=MediaPipelineOperations(
            synthesize_audio=operation("synthesize_audio"),
            confirm_audio=operation("confirm_audio"),
            render_video=operation("render_video"),
        ),
    )
    db = object()
    services = ProjectPipelineServices(operations, db, "project-1")

    assert services.storyboard_script()["operation"] == "storyboard_script"
    assert services.storyboard_visual()["operation"] == "storyboard_visual"
    assert services.storyboard_compose()["operation"] == "storyboard_compose"
    assert services.image_prompts()["operation"] == "image_prompts"
    assert services.generate_image("slide-1", "prompt")["operation"] == "generate_image"
    assert services.confirm_images()["operation"] == "confirm_images"
    assert services.mask_manifest()["operation"] == "mask_manifest"
    assert services.repair_mask_manifest()["operation"] == "repair_mask_manifest"
    assert services.build_mask_assets({"slides": []})["operation"] == "build_mask_assets"
    assert services.narration()["operation"] == "narration"
    assert services.repair_narration()["operation"] == "repair_narration"
    assert services.init_narration()["operation"] == "init_narration"
    assert services.annotate_narration({"slide-1": []})["operation"] == "annotate_narration"
    assert services.save_narration({"slide-1": []})["operation"] == "save_narration"
    assert services.synthesize_audio()["operation"] == "synthesize_audio"
    assert services.confirm_audio()["operation"] == "confirm_audio"
    assert services.render_video()["operation"] == "render_video"

    assert calls[0] == ("storyboard_script", ("project-1", {}, db), {})
    assert calls[4] == (
        "generate_image",
        ("project-1",),
        {"slide_id": "slide-1", "prompt": "prompt", "preview": False, "db": db},
    )
    assert calls[8] == (
        "build_mask_assets",
        ("project-1", {"slides": []}),
        {"build_assets": True, "db": db},
    )
    assert calls[15] == (
        "confirm_audio",
        ("project-1", {"confirmation_mode": "automatic_technical"}, db),
        {},
    )
    assert not hasattr(services, "server")
    assert not hasattr(services, "server_module")


def test_pipeline_facade_source_has_no_server_module_dependency() -> None:
    source = (ROOT / "pipeline_services.py").read_text(encoding="utf-8")
    assert "ModuleType" not in source
    assert "server_module" not in source
    assert "self.server" not in source
