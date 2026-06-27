"""Static contract check for runtime_bootstrap.py.

The runtime bootstrap is responsible for loading additive bridge modules before
FastAPI's root static mount can shadow their API routes. This check keeps the
critical Step 2 / Step 3 / AI Mask / One-click bridges and ready-route list from
regressing silently.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_PATH = ROOT / "runtime_bootstrap.py"

REQUIRED_MODULES = {
    "runtime_settings_mask",
    "runtime_ai_mask",
    "runtime_storyboard_background",
    "runtime_project_profile_lightweight",
    "runtime_project_profile_templates_override",
    "runtime_step3_image_style",
    "runtime_step3_image_style_state",
    "runtime_step2_storyboard_settings",
    "runtime_one_click_orchestrator",
    "runtime_one_click_step3_style_patch",
}

REQUIRED_READY_ROUTES = {
    ("/api/settings/ai-mask", "GET"),
    ("/api/project-profile/templates", "GET"),
    ("/api/projects/{project_id}/one-click-generate", "POST"),
    ("/api/projects/{project_id}/one-click-generate/status", "GET"),
    ("/api/projects/{project_id}/storyboard-background", "GET"),
    ("/api/projects/{project_id}/steps/3/image-style", "GET"),
    ("/api/projects/{project_id}/steps/3/image-style/reverse", "POST"),
    ("/api/projects/{project_id}/steps/3/image-style/reference-images", "GET"),
    ("/api/projects/{project_id}/steps/3/image-style/reference-images", "POST"),
    ("/api/projects/{project_id}/steps/3/image-style/reference-images", "DELETE"),
    ("/api/projects/{project_id}/steps/5/ai-mask/annotate", "POST"),
}


def _assignment_value(module: ast.Module, name: str) -> Any:
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        return ast.literal_eval(node.value)
    raise AssertionError(f"Missing {name} assignment in runtime_bootstrap.py")


def _literal_string_collection(module: ast.Module, name: str) -> set[str]:
    value = _assignment_value(module, name)
    if not isinstance(value, (list, tuple, set)):
        raise AssertionError(f"{name} must be a list/tuple/set literal")
    return {str(item) for item in value}


def _literal_route_mapping(module: ast.Module, name: str) -> set[tuple[str, str]]:
    value = _assignment_value(module, name)
    if not isinstance(value, dict):
        raise AssertionError(f"{name} must be a dict literal")
    routes: set[tuple[str, str]] = set()
    for path, methods in value.items():
        if not isinstance(methods, (list, tuple, set)):
            raise AssertionError(f"{name}[{path!r}] must be a list/tuple/set literal")
        for method in methods:
            routes.add((str(path), str(method).upper()))
    return routes


def _format_route(route: tuple[str, str]) -> str:
    path, method = route
    return f"{method} {path}"


def main() -> None:
    tree = ast.parse(BOOTSTRAP_PATH.read_text(encoding="utf-8"), filename=str(BOOTSTRAP_PATH))
    modules = _literal_string_collection(tree, "RUNTIME_MODULES")
    routes = _literal_route_mapping(tree, "EXPECTED_RUNTIME_ROUTES")

    missing_modules = sorted(REQUIRED_MODULES - modules)
    missing_routes = sorted(REQUIRED_READY_ROUTES - routes, key=_format_route)
    problems = []
    if missing_modules:
        problems.append("Missing runtime modules:\n" + "\n".join(missing_modules))
    if missing_routes:
        problems.append("Missing ready routes:\n" + "\n".join(_format_route(route) for route in missing_routes))
    if problems:
        raise SystemExit("\n\n".join(problems))
    print("Runtime bootstrap contract passed.")


if __name__ == "__main__":
    main()
