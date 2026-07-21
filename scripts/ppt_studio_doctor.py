#!/usr/bin/env python3
"""Run consolidated health checks for PPT Visualization Studio.

Typical usage from the repository root:

    python scripts/ppt_studio_doctor.py

With a project artifact check:

    python scripts/ppt_studio_doctor.py --run-dir runs/<project_id> --stage step8

The doctor runs existing focused checks instead of duplicating their logic:

- Python startup hook loading
- runtime hotfix behavior
- optional settings secret masking behavior
- safe Step 1 dead-code cleanup preview
- optional run_dir artifact checks

Exit code is non-zero when a required check fails.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STAGE_ORDER = ["step1", "step2", "step3", "step5", "step6", "step7", "step8"]


@dataclass
class CheckResult:
    name: str
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    required: bool = True

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except Exception:
        return str(path)


def run_check(name: str, command: list[str], *, env: dict[str, str] | None = None, required: bool = True) -> CheckResult:
    print(f"\n==> {name}")
    print("$ " + " ".join(command))
    result = subprocess.run(
        command,
        cwd=str(REPO_ROOT),
        env=env or os.environ.copy(),
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.stderr.strip():
        print(result.stderr.rstrip(), file=sys.stderr)
    status = "PASS" if result.returncode == 0 else ("FAIL" if required else "WARN")
    print(f"{status} {name}")
    return CheckResult(
        name=name,
        command=command,
        returncode=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
        required=required,
    )


def check_required_files() -> CheckResult:
    required_paths = [
        "sitecustomize.py",
        "usercustomize.py",
        "runtime_security.py",
        "runtime_settings_mask.py",
        "scripts/check_python_startup_hooks.py",
        "scripts/check_runtime_hotfixes.py",
        "scripts/check_runtime_settings_mask.py",
        "scripts/cleanup_step1_dead_code.py",
        "scripts/check_smoke_artifacts.py",
        "docs/e2e_smoke_test_checklist.md",
        "docs/runtime_hotfixes_and_security.md",
    ]
    missing = [path for path in required_paths if not (REPO_ROOT / path).exists()]
    stdout = "\n".join(f"found {path}" for path in required_paths if path not in missing)
    if missing:
        stdout += "\n" + "\n".join(f"missing {path}" for path in missing)
    print("\n==> required repository files")
    print(stdout)
    return CheckResult(
        name="required repository files",
        command=["internal:file-check"],
        returncode=1 if missing else 0,
        stdout=stdout,
        stderr="",
        required=True,
    )


def env_report() -> None:
    print("\n==> environment summary")
    keys = [
        "PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES",
        "PPT_STUDIO_ACCESS_TOKEN",
        "PPT_STUDIO_ALLOWED_ORIGINS",
        "PPT_STUDIO_MASK_SETTINGS_SECRETS",
        "PPT_STUDIO_SECURE_COOKIE",
    ]
    for key in keys:
        value = os.environ.get(key, "")
        if key == "PPT_STUDIO_ACCESS_TOKEN" and value:
            value = f"<set:{len(value)} chars>"
        print(f"{key}={value or '<unset>'}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", help="optional project run directory to structurally check")
    parser.add_argument("--stage", choices=STAGE_ORDER, default="step8", help="highest stage for --run-dir artifact checks")
    parser.add_argument(
        "--skip-step1-cleanup-check",
        action="store_true",
        help="skip scripts/cleanup_step1_dead_code.py --check",
    )
    args = parser.parse_args()

    if not (REPO_ROOT / "server.py").exists():
        print(f"FAIL expected to run inside repository root containing server.py: {REPO_ROOT}")
        return 1

    env_report()
    checks: list[CheckResult] = [check_required_files()]

    checks.append(
        run_check(
            "Python startup hooks",
            [sys.executable, "scripts/check_python_startup_hooks.py"],
        )
    )
    checks.append(
        run_check(
            "runtime hotfix behavior",
            [sys.executable, "scripts/check_runtime_hotfixes.py"],
        )
    )

    mask_env = os.environ.copy()
    mask_env["PPT_STUDIO_MASK_SETTINGS_SECRETS"] = "1"
    checks.append(
        run_check(
            "settings secret masking",
            [sys.executable, "scripts/check_runtime_settings_mask.py"],
            env=mask_env,
        )
    )

    if not args.skip_step1_cleanup_check:
        checks.append(
            run_check(
                "Step 1 dead-code cleanup safety preview",
                [sys.executable, "scripts/cleanup_step1_dead_code.py", "--check"],
                # This is a required check because the cleanup script is expected
                # to either prove the edit is safe or report that the block is
                # already absent.
                required=True,
            )
        )

    if args.run_dir:
        run_dir = Path(args.run_dir)
        checks.append(
            run_check(
                f"smoke artifacts through {args.stage}",
                [sys.executable, "scripts/check_smoke_artifacts.py", "--run-dir", rel(run_dir), "--stage", args.stage],
            )
        )

    failed = [check for check in checks if check.required and not check.ok]
    warned = [check for check in checks if not check.required and not check.ok]

    print("\n==> summary")
    print(f"required checks: {len([c for c in checks if c.required])}")
    print(f"failed required checks: {len(failed)}")
    print(f"warning checks: {len(warned)}")
    if failed:
        for check in failed:
            print(f"FAIL {check.name}")
        return 1
    print("OK PPT Studio doctor checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
