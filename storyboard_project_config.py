"""Project snapshot adapters used by the Step 2 storyboard service."""

from __future__ import annotations

from typing import Any, Callable, Optional

from fastapi import HTTPException

from project_config_runtime import (
    ProjectConfigBindingError,
    get_config_value,
    resolve_project_model_binding,
)


def read_step2_prompts_for_project(
    project: Any,
    *,
    read_prompts: Callable[[Any], dict[str, str]],
) -> dict[str, str]:
    """Overlay package prompt sections on the existing Step 2 templates."""
    prompts = read_prompts(project)
    for section_name, system_key, output_key in (
        ("storyboard", "script_system", "script_output_example"),
        ("visualization", "visual_system", "visual_output_example"),
    ):
        section = get_config_value(project, f"prompts.{section_name}")
        if not isinstance(section, dict):
            continue
        system = section.get(system_key, section.get("system_content"))
        output = section.get(output_key, section.get("output_example"))
        if isinstance(system, str) and system.strip():
            prompts[system_key] = system.strip()
        if isinstance(output, str) and output.strip():
            prompts[output_key] = output.strip()
    return prompts


def resolve_step2_llm(
    project: Any,
    binding_name: str,
    *,
    resolve_model_connection: Optional[Callable[[str, int], Any]],
    get_credential: Optional[Callable[[str], Any]],
    parse_int_setting: Callable[[Any, int, int, int], int],
    fallback: Callable[[], tuple[str, Optional[str], str, float, int]],
) -> tuple[str, Optional[str], str, float, int]:
    """Resolve a project-pinned Step 2 text model or use the legacy fallback."""
    selected_name = binding_name
    if binding_name == "visualization" and get_config_value(
        project, "model_bindings.visualization"
    ) is None:
        selected_name = "storyboard"
    try:
        binding = resolve_project_model_binding(
            project,
            selected_name,
            expected_kind="text",
            resolve_model_connection=resolve_model_connection,
            get_credential=get_credential,
        )
    except ProjectConfigBindingError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if binding is None:
        return fallback()
    try:
        planning_temp = min(float(binding.public_config.get("temperature", 0.7)), 0.2)
    except (TypeError, ValueError):
        planning_temp = 0.2
    planning_max_tokens = parse_int_setting(
        binding.public_config.get("max_tokens", 50000), 50000, 1024, 64000
    )
    return binding.api_key, binding.endpoint, binding.model, planning_temp, planning_max_tokens
