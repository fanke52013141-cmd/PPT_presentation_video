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
            "template_id": "government_brief",
            "version": 1,
            "reference_policy": "preferred",
            "minimum_reference_images": 1,
        },
        "subtitle": {"enabled": True},
        "mask": {"enabled": True},
        "automation": {
            "mode": "auto",
            # 项目级子配额：上游额度是**网关全局**的（生图默认 500 请求/分钟），
            # 多账号同时生成时由 generation_governor 统一排队，项目配置不能
            # 把它当成唯一闸门。
            "image_concurrency": 5,
            "ai_narration_annotation": False,
            # Automatic AI Mask is opt-in.  A newly created package keeps the
            # existing full-frame production behavior until its owner enables
            # the additional annotation stage explicitly.
            "ai_mask_annotation": False,
        },
        "tts": {
            # MiniMax 的网关额度是 10 请求/分钟，而单页**异步**合成要消耗
            # 上传 + 提交 + 取回 + 轮询约 4-7 次请求，所以真正决定页速的是额度
            # 而不是线程数；并发开到 10 只会造成超发与被限流。
            "concurrency": 4,
            # Seed Audio has a lower provider concurrency entitlement than
            # MiniMax.  Keep this separate so a package can safely use either
            # provider without changing MiniMax's established fan-out.
            "seed_audio_concurrency": 5,
            "requests_per_minute": 10,
        },
        "render": {"acceleration": "auto", "output_formats": ["video"]},
    }
    return deepcopy(payload)
