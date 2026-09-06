"""Canonical defaults used when a new creation package is started.

The defaults stay owned by the modules that execute each pipeline stage.  This
module only assembles them for the creation-package editor; it does not copy
credentials or model connections into a package.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


def default_creation_config_payload() -> dict[str, Any]:
    """Return a fresh, editable payload populated from current built-ins."""
    from ai_mask_engine import DEFAULT_METHODOLOGY, DEFAULT_OUTPUT_STRUCTURE
    from article_service import DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT
    from narration_service import (
        DEFAULT_NARRATION_ANNOTATION_OUTPUT_EXAMPLE,
        DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT,
    )
    from repository_paths import STEP3_IMAGE_PROMPT_TEMPLATE_PATH
    from storyboard_prompt_templates import default_step2_prompts, read_prompt_template

    step2 = default_step2_prompts()
    ai_mask_system = "\n\n".join(
        [
            str(DEFAULT_METHODOLOGY).strip(),
            "--- OUTPUT STRUCTURE / 输出结构 ---",
            str(DEFAULT_OUTPUT_STRUCTURE).strip(),
        ]
    ).strip()
    payload: dict[str, Any] = {
        "schema_version": "creation_config_v1",
        "prompts": {
            "article_generation": {
                "system_content": DEFAULT_ARTICLE_GENERATION_SYSTEM_CONTENT.strip(),
            },
            "storyboard": {
                "system_content": step2["script_system"],
                "output_example": step2["script_output_example"],
            },
            "visualization": {
                "system_content": step2["visual_system"],
                "output_example": step2["visual_output_example"],
            },
            "image_generation": {
                "system_content": read_prompt_template(STEP3_IMAGE_PROMPT_TEMPLATE_PATH),
            },
            "ai_mask": {
                "system_content": ai_mask_system,
            },
            "narration_annotation": {
                "system_content": DEFAULT_NARRATION_ANNOTATION_SYSTEM_CONTENT.strip(),
                "output_example": DEFAULT_NARRATION_ANNOTATION_OUTPUT_EXAMPLE.strip(),
            },
        },
        "model_bindings": {},
        "image_style": {
            "template_id": "handdrawn",
            "version": 1,
            "reference_policy": "preferred",
            "minimum_reference_images": 1,
        },
        "subtitle": {"enabled": True},
        "mask": {"enabled": True},
        "automation": {"image_concurrency": 5},
        "tts": {"concurrency": 10, "requests_per_minute": 10},
        "render": {"acceleration": "auto"},
    }
    return deepcopy(payload)
