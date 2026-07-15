"""Explicit ordered registration for project profile and Step 3 style routes."""

from __future__ import annotations

from types import ModuleType

import runtime_project_profile
import runtime_project_profile_lightweight
import runtime_project_profile_templates_override
import runtime_project_style_references
import runtime_project_style_reference_manager
import runtime_image_style_reverse
import runtime_step3_image_style
import runtime_step3_image_style_state


REGISTRATION_STEPS = (
    ("project_profile", runtime_project_profile._register),
    ("project_profile_lightweight", runtime_project_profile_lightweight._register),
    ("project_profile_templates_override", runtime_project_profile_templates_override._register),
    ("project_style_references", runtime_project_style_references._register),
    ("project_style_reference_manager", runtime_project_style_reference_manager._register),
    ("image_style_reverse", runtime_image_style_reverse._register),
    ("step3_image_style", runtime_step3_image_style._register),
    ("step3_image_style_state", runtime_step3_image_style_state._register),
)


def register_project_style_routes(server_module: ModuleType) -> None:
    for name, register in REGISTRATION_STEPS:
        if register(server_module) is not True:
            raise RuntimeError(f"project style route registration failed at {name}")
