"""Project-level AI Mask annotation task service."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Callable

import ai_mask_engine
from ai_mask_config import get_ai_mask_settings, read_ai_mask_prompts


@dataclass(frozen=True)
class AiMaskDependencies:
    get_setting: Callable[..., Any]
    get_openai_client: Callable[..., Any]
    reveal_lock_for: Callable[[Any], Any]
    write_project_log: Callable[..., None]
    read_style_tokens_data: Callable[[], dict[str, Any]]
    step2_llm_vendor_options: Callable[..., dict[str, Any]]
    clean_json_markdown: Callable[[str], str]
    is_timeout_exception: Callable[[BaseException], bool]
    vision_matcher: Callable[..., dict[str, Any] | None]
    logger: logging.Logger


class AiMaskTaskService:
    def __init__(self, dependencies: AiMaskDependencies) -> None:
        self.dependencies = dependencies
        # The algorithm receives a frozen capability record, never the server
        # module or FastAPI application.
        self.engine_dependencies = ai_mask_engine.AiMaskEngineDependencies(
            get_setting=dependencies.get_setting,
            get_openai_client=dependencies.get_openai_client,
            read_style_tokens_data=dependencies.read_style_tokens_data,
            step2_llm_vendor_options=dependencies.step2_llm_vendor_options,
            clean_json_markdown=dependencies.clean_json_markdown,
            is_timeout_exception=dependencies.is_timeout_exception,
            write_project_log=dependencies.write_project_log,
            logger=dependencies.logger,
        )

    def annotate_project(
        self,
        project: Any,
        settings_override: dict[str, Any] | None = None,
        slide_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        settings = get_ai_mask_settings()
        if isinstance(settings_override, dict):
            settings = ai_mask_engine.normalize_settings(
                {**settings, **settings_override}
            )
        methodology, output_structure = read_ai_mask_prompts()
        with self.dependencies.reveal_lock_for(project):
            result = ai_mask_engine._annotate_project(
                self.engine_dependencies,
                project,
                settings,
                methodology,
                output_structure,
                self.dependencies.vision_matcher,
                slide_ids,
            )
        try:
            self.dependencies.write_project_log(
                project,
                "ai_mask_annotation",
                **result,
            )
        except Exception:
            self.dependencies.logger.exception(
                "Failed to write AI Mask annotation log for %s",
                getattr(project, "id", ""),
            )
        return result


_TASK_SERVICE: AiMaskTaskService | None = None


def configure_ai_mask_task_service(
    dependencies: AiMaskDependencies,
) -> AiMaskTaskService:
    global _TASK_SERVICE
    _TASK_SERVICE = AiMaskTaskService(dependencies)
    return _TASK_SERVICE


def get_ai_mask_task_service() -> AiMaskTaskService:
    if _TASK_SERVICE is None:
        raise RuntimeError("AI Mask task service has not been configured")
    return _TASK_SERVICE
