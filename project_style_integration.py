"""Composition helpers that connect project style resources to app workflows."""

from __future__ import annotations

from typing import Any

from project_style_context import get_project_style_context
from project_style_template_service import (
    export_portable_templates,
    import_portable_templates,
    materialize_creation_config_style,
    validate_portable_templates,
)


def export_current_project_style_templates() -> dict[str, Any]:
    """Export the active account's reusable image-style resources."""
    return export_portable_templates(get_project_style_context())


def validate_current_project_style_templates(value: Any) -> None:
    """Validate portable styles before a configuration package is imported."""
    validate_portable_templates(get_project_style_context(), value)


def import_current_project_style_templates(value: Any) -> list[dict[str, Any]]:
    """Import portable styles into the active account's resource library."""
    return import_portable_templates(get_project_style_context(), value)


def materialize_project_image_style(
    project: Any,
    binding: dict[str, Any],
) -> dict[str, Any] | None:
    """Snapshot a selected reusable image style for a new project."""
    return materialize_creation_config_style(
        get_project_style_context(),
        project,
        binding,
    )
