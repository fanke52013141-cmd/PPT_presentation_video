#!/usr/bin/env python3
"""Run the repository's canonical local and CI checks."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    display = " ".join(command)
    print(f"\n==> {display}", flush=True)
    process_env = os.environ.copy() if env is None else env.copy()
    existing_pythonpath = process_env.get("PYTHONPATH", "")
    process_env["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    subprocess.run(command, cwd=cwd, env=process_env, check=True)


def python_check(path: Path) -> None:
    run([sys.executable, str(path.relative_to(ROOT))])


def quick_checks() -> None:
    run([
        sys.executable,
        "-m",
        "compileall",
        "-q",
        "start_server.py",
        "app_security.py",
        "artifact_fingerprint.py",
        "diagnostics_routes.py",
        "one_click_orchestrator.py",
        "storyboard_background.py",
        "storyboard_background_render.py",
        "server.py",
        "pipeline_lifecycle.py",
        "pipeline_state.py",
        "project_storage.py",
        "project_style_routes.py",
        "tts_artifacts.py",
        "visual_provenance.py",
        "scripts",
        "checks",
    ])
    for source in sorted((ROOT / "static").glob("*.js")):
        run(["node", "--check", str(source.relative_to(ROOT))])
    python_check(ROOT / "checks" / "test_step_ownership_contract.py")
    run(["node", "checks/test_visible_flow.js"])
    run(["node", "checks/test_frontend_quality.js"])
    python_check(ROOT / "checks" / "test_source_hardening.py")
    python_check(ROOT / "checks" / "test_generalized_settings.py")
    python_check(ROOT / "checks" / "test_subtitle_style.py")
    python_check(ROOT / "scripts" / "check_python_startup_hooks.py")
    python_check(ROOT / "scripts" / "check_runtime_hotfixes.py")
    masked_env = os.environ.copy()
    masked_env["PPT_STUDIO_MASK_SETTINGS_SECRETS"] = "1"
    run([sys.executable, "scripts/check_runtime_settings_mask.py"], env=masked_env)


def full_checks() -> None:
    quick_checks()
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
