"""Static contract check for runtime_bootstrap.py.

The runtime bootstrap is responsible for loading additive bridge modules before
FastAPI's root static mount can shadow their API routes. This check keeps the
critical Step 2 / Step 3 / AI Mask / One-click bridges and ready-route list from
regressing silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

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

REQUIRED_READY_PATHS = {
    "/api/settings/ai-mask",
    "/api/project-profile/templates",
    "/api/projects/{project_id}/one-click-generate",
    "/api/projects/{project_id}/storyboard-background",
    "/api/projects/{project_id}/steps/3/image-style",
    "/api/projects/{project_id}/steps/3/image-style/reverse",
    "/api/projects/{project_id}/steps/3/image-style/reference-images",
    "/api/projects/{project_id}/steps/5/ai-mask/annotate",
}


def _literal_assignment(module: ast.Module, name: str) -> set[str]:
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, (list, tuple, set)):
            raise AssertionError(f"{name} must be a list/tuple/set literal")
        return {str(item) for item in value}
    raise AssertionError(f"Missing {name} assignment in runtime_bootstrap.py")


def main() -> None:
    tree = ast.parse(BOOTSTRAP_PATH.read_text(encoding="utf-8"), filename=str(BOOTSTRAP_PATH))
    modules = _literal_assignment(tree, "RUNTIME_MODULES")
    paths = _literal_assignment(tree, "EXPECTED_RUNTIME_PATHS")

    missing_modules = sorted(REQUIRED_MODULES - modules)
    missing_paths = sorted(REQUIRED_READY_PATHS - paths)
    problems = []
    if missing_modules:
        problems.append("Missing runtime modules:\n" + "\n".join(missing_modules))
    if missing_paths:
        problems.append("Missing ready paths:\n" + "\n".join(missing_paths))
    if problems:
        raise SystemExit("\n\n".join(problems))
    print("Runtime bootstrap contract passed.")


if __name__ == "__main__":
    main()
