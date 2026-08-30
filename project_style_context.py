"""Explicit dependencies shared by project-style services and routes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ProjectStyleDependencies:
    get_setting: Callable[..., Any]
    update_settings: Callable[[dict[str, Any]], Any]
    get_openai_client: Callable[..., Any]
    generate_image_response: Callable[..., Any]
    extract_image_bytes_from_response: Callable[..., bytes]
    process_and_save_image: Callable[..., Any]
    write_project_log: Callable[..., None]
    build_image_style_prompt: Callable[[dict[str, Any]], str]
    read_style_tokens_data: Callable[[], dict[str, Any]]
    compose_step3_single_slide_prompt: Callable[..., str]
    read_step3_image_system_content: Callable[[], str]
    compact_slide_element_lines: Callable[[dict[str, Any]], list[str]]
    is_seedream_image_model: Callable[..., bool]
    http_exception: type[Exception]
    image_class: Any
    data_dir: Path
    repo_root: Path
    handdrawn_style_tokens_path: Path


_CONTEXT: ProjectStyleDependencies | None = None


def configure_project_style_context(
    dependencies: ProjectStyleDependencies,
) -> ProjectStyleDependencies:
    global _CONTEXT
    _CONTEXT = dependencies
    return _CONTEXT


def get_project_style_context() -> ProjectStyleDependencies:
    if _CONTEXT is None:
        raise RuntimeError("Project style context has not been configured")
    return _CONTEXT
