#!/usr/bin/env python3
"""Run the repository's canonical local and CI checks."""

from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
QUICK_PYTHON_CHECKS = (
    ROOT / "checks" / "test_step_ownership_contract.py",
    ROOT / "checks" / "test_source_hardening.py",
    ROOT / "checks" / "test_generalized_settings.py",
    ROOT / "checks" / "test_subtitle_style.py",
)


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    display = " ".join(command)
    print(f"\n==> {display}", flush=True)
    process_env = os.environ.copy() if env is None else env.copy()
    existing_pythonpath = process_env.get("PYTHONPATH", "")
    process_env["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    subprocess.run(command, cwd=cwd, env=process_env, check=True)


def python_check(path: Path) -> None:
    run([sys.executable, str(path.relative_to(ROOT))])


def standalone_python_checks() -> list[Path]:
    """Return script-style checks that pytest cannot discover."""
    result: list[Path] = []
    for path in sorted((ROOT / "checks").glob("test_*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        has_pytest_tests = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
            for node in module.body
        )
        if not has_pytest_tests:
            result.append(path)
    return result


def quick_checks() -> None:
    run([
        sys.executable,
        "-m",
        "compileall",
        "-q",
        "start_server.py",
        "ai_mask_config.py",
        "ai_mask_assignment.py",
        "ai_mask_component_detection.py",
        "ai_mask_contracts.py",
        "ai_mask_engine.py",
        "ai_mask_manifest_apply.py",
        "ai_mask_routes.py",
        "ai_mask_semantic_matcher.py",
        "ai_mask_service.py",
        "ai_provider_service.py",
        "app_middleware.py",
        "app_security.py",
        "artifact_fingerprint.py",
        "artifact_registry.py",
        "article_routes.py",
        "article_service.py",
        "config_portability_service.py",
        "database.py",
        "database_migrations.py",
        "diagnostics_routes.py",
        "invalidation_service.py",
        "json_llm_service.py",
        "mask_editor_routes.py",
        "mask_manifest_service.py",
        "mask_preview_service.py",
        "one_click_orchestrator.py",
        "one_click_resume_policy.py",
        "one_click_routes.py",
        "narration_routes.py",
        "narration_audio_service.py",
        "narration_service.py",
        "pptx_export.py",
        "pptx_routes.py",
        "pptx_service.py",
        "project_profile_service.py",
        "project_profile_store.py",
        "project_path_service.py",
        "project_routes.py",
        "project_service.py",
        "project_style_context.py",
        "project_style_reference_service.py",
        "project_style_reference_store.py",
        "storyboard_background.py",
        "storyboard_background_render.py",
        "storyboard_routes.py",
        "storyboard_planning.py",
        "storyboard_llm.py",
        "storyboard_profiles.py",
        "storyboard_prompt_templates.py",
        "storyboard_service.py",
        "server.py",
        "settings_routes.py",
        "settings_service.py",
        "pipeline_lifecycle.py",
        "pipeline_state.py",
        "project_storage.py",
        "project_style_routes.py",
        "project_style_template_service.py",
        "image_style_reverse_service.py",
        "step3_image_style_service.py",
        "template_utils.py",
        "reveal_manifest_service.py",
        "tts_artifacts.py",
        "tts_provider_service.py",
        "tts_routes.py",
        "tts_service.py",
        "visual_provenance.py",
        "visual_contract_service.py",
        "video_artifact_service.py",
        "video_contracts.py",
        "video_job_store.py",
        "video_render_service.py",
        "video_routes.py",
        "remotion_runner.py",
        "runtime_support.py",
        "project_runtime_service.py",
        "repository_paths.py",
        "route_inventory.py",
        "scripts",
        "checks",
    ])
    for source in sorted((ROOT / "static").glob("*.js")):
        run(["node", "--check", str(source.relative_to(ROOT))])
    python_check(QUICK_PYTHON_CHECKS[0])
    run(["node", "checks/test_visible_flow.js"])
    run(["node", "checks/test_frontend_quality.js"])
    run(["node", "checks/test_subtitle_paging.js"])
    run(["node", "checks/test_ai_mask_auto_state.js"])
    python_check(ROOT / "scripts" / "check_source_registration_contract.py")
    python_check(ROOT / "scripts" / "check_static_extension_references.py")
    python_check(ROOT / "checks" / "test_source_hardening.py")
    for path in QUICK_PYTHON_CHECKS[2:]:
        python_check(path)
    run([
        sys.executable,
        "-m",
        "pytest",
        "checks/test_runtime_support.py",
        "checks/test_project_runtime_service.py",
        "checks/test_repository_paths.py",
        "checks/test_server_composition_boundaries.py",
        "checks/test_architecture_size_boundaries.py",
        "checks/test_route_inventory.py",
        "checks/test_tts_provider_service.py",
        "checks/test_tts_secret_transport.py",
        "-q",
    ])
    run([
        sys.executable,
        "-m",
        "pytest",
        "checks/test_ai_provider_service.py",
        "checks/test_image_upload_limits.py",
        "-q",
    ])
    run([
        sys.executable,
        "-m",
        "pytest",
        "checks/test_settings_services.py",
        "checks/test_config_export_security.py",
        "checks/test_config_import_limits.py",
        "-q",
    ])
    run([
        sys.executable,
        "-m",
        "pytest",
        "checks/test_video_render_components.py",
        "checks/test_persistent_video_jobs.py",
        "checks/test_e2e_entrypoints.py",
        "-q",
    ])
    run([
        sys.executable,
        "-m",
        "pytest",
        "checks/test_storyboard_routes.py",
        "-q",
    ])
    run([
        sys.executable,
        "-m",
        "pytest",
        "checks/test_article_service.py",
        "-q",
    ])
    run([
        sys.executable,
        "-m",
        "pytest",
        "checks/test_ai_mask_registration.py",
        "checks/test_ai_mask_services.py",
        "checks/test_ai_mask_automation.py",
        "-q",
    ])
    run([
        sys.executable,
        "-m",
        "pytest",
        "checks/test_mask_editor_services.py",
        "checks/test_step3_service_boundaries.py",
        "-q",
    ])
    run([
        sys.executable,
        "-m",
        "pytest",
        "checks/test_narration_audio_service.py",
        "checks/test_visual_contract_service.py",
        "checks/test_narration_tts_routes.py",
        "-q",
    ])
    run([
        sys.executable,
        "-m",
        "pytest",
        "checks/test_project_service.py",
        "checks/test_project_routes.py",
        "-q",
    ])
    python_check(ROOT / "scripts" / "check_python_startup_hooks.py")
    python_check(ROOT / "scripts" / "check_runtime_hotfixes.py")
    masked_env = os.environ.copy()
    masked_env["PPT_STUDIO_MASK_SETTINGS_SECRETS"] = "1"
    run([sys.executable, "scripts/check_runtime_settings_mask.py"], env=masked_env)


def full_checks() -> None:
    quick_checks()
    quick_check_set = set(QUICK_PYTHON_CHECKS)
    for path in standalone_python_checks():
        if path not in quick_check_set:
            python_check(path)
    run([sys.executable, "-m", "pytest", "-q"])


def remotion_check() -> None:
    remotion = ROOT / "scripts" / "remotion"
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npm or not npx:
        raise SystemExit("npm and npx are required for --with-remotion")
    run([npm, "ci"], cwd=remotion)
    run([npx, "tsc", "--noEmit", "-p", "tsconfig.json"], cwd=remotion)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--level", choices=("quick", "full"), default="quick")
    parser.add_argument("--with-remotion", action="store_true")
    args = parser.parse_args()
    quick_checks() if args.level == "quick" else full_checks()
    if args.with_remotion:
        remotion_check()
    print("\nAll requested checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
