"""Explicit dependencies shared by project-style services and routes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable


@dataclass(frozen=True)
class ProjectStyleDependencies:
    get_setting: Callable[..., Any]
    update_settings: Callable[[dict[str, Any]], Any]
    get_openai_client: Callable[..., Any]
    generate_image_response: Callable[..., Any]
    extract_image_bytes_from_response: Callable[..., bytes]
    process_and_save_image: Callable[[bytes, str], Any]
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


_CONTEXT: SimpleNamespace | None = None


def configure_project_style_context(
    dependencies: ProjectStyleDependencies,
) -> SimpleNamespace:
    global _CONTEXT
    _CONTEXT = SimpleNamespace(
        get_setting=dependencies.get_setting,
        update_settings=dependencies.update_settings,
        get_openai_client=dependencies.get_openai_client,
        generate_image_response=dependencies.generate_image_response,
        extract_image_bytes_from_response=dependencies.extract_image_bytes_from_response,
        process_and_save_image=dependencies.process_and_save_image,
        write_project_log=dependencies.write_project_log,
        build_image_style_prompt=dependencies.build_image_style_prompt,
        read_style_tokens_data=dependencies.read_style_tokens_data,
        compose_step3_single_slide_prompt=dependencies.compose_step3_single_slide_prompt,
        read_step3_image_system_content=dependencies.read_step3_image_system_content,
        compact_slide_element_lines=dependencies.compact_slide_element_lines,
        is_seedream_image_model=dependencies.is_seedream_image_model,
        HTTPException=dependencies.http_exception,
        Image=dependencies.image_class,
        DATA_DIR=dependencies.data_dir,
        REPO_ROOT=dependencies.repo_root,
        HANDDRAWN_STYLE_TOKENS_PATH=dependencies.handdrawn_style_tokens_path,
    )
    return _CONTEXT


def get_project_style_context() -> SimpleNamespace:
    if _CONTEXT is None:
        raise RuntimeError("Project style context has not been configured")
    return _CONTEXT
