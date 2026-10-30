"""Registered downstream effects for project edits.

Every new invalidation reason must be added here.  This is the source used by
the invalidation service and the impact-registry check; it describes current
effects, including effects that still need narrowing in later migrations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImpactRule:
    source: str
    scope: str
    affected: tuple[str, ...]
    policy: str


IMPACT_RULES: dict[str, ImpactRule] = {
    "stage_already_completed": ImpactRule("step confirmation", "none", (), "reuse"),
    "stage_completed": ImpactRule("step confirmation", "stage", (), "reuse"),
    "stage_started": ImpactRule("stage execution", "stage", (), "reuse"),
    "article_changed": ImpactRule("article content", "project", ("storyboard",), "review"),
    "storyboard_changed": ImpactRule("visual contract", "project", ("images", "Mask", "audio", "output"), "review"),
    "storyboard_script_changed": ImpactRule("storyboard speech script", "project", ("storyboard",), "review"),
    "storyboard_visual_changed": ImpactRule("slide visual plan", "slide", ("images", "Mask", "annotation geometry", "output"), "review"),
    "storyboard_narration_changed": ImpactRule("slide narration plan", "slide", ("audio confirmation", "annotation timing", "output"), "review"),
    "storyboard_structure_changed": ImpactRule("slide order or removal", "project", ("output",), "recompose"),
    "storyboard_empty": ImpactRule("visual contract", "project", ("images", "Mask", "audio", "output"), "review"),
    "slide_image_changed": ImpactRule("slide image, including reviewed regional candidate repair", "slide", ("Mask", "annotation geometry", "output"), "review"),
    "subtitle_style_changed": ImpactRule("subtitle style", "project", ("output",), "recompose"),
    "mask_content_changed": ImpactRule("Mask manifest", "project", ("output",), "recompose"),
    "subtitle_visibility_changed": ImpactRule("subtitle visibility", "project", ("output",), "recompose"),
    "video_background_changed": ImpactRule("video background", "project", ("reveal layers", "output"), "rebuild"),
    "narration_synthesis_started": ImpactRule("audio generation", "project", (), "reuse"),
    "audio_artifacts_changed": ImpactRule("generated audio", "slide", ("audio confirmation", "annotation timing", "output"), "review"),
    "narration_content_changed": ImpactRule("narration content", "project", ("audio confirmation", "annotation timing", "output"), "review"),
    "annotation_changed": ImpactRule("annotation content, selected OCR text or annotation style", "slide", ("output",), "recompose"),
    "digital_human_changed": ImpactRule("digital human configuration or media", "project", ("output",), "recompose"),
    "digital_human_audio_changed": ImpactRule("presenter lip-sync audio", "slide", ("digital human media", "output"), "review"),
}
