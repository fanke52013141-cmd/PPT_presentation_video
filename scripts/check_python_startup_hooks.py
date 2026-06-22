#!/usr/bin/env python3
"""Verify that Python auto-loads the repository startup hooks.

Run from the repository root:

    python scripts/check_python_startup_hooks.py

This check launches a child Python interpreter from the repository root and
verifies that Python startup imports the expected hook modules:

- sitecustomize
- runtime_security, imported by sitecustomize
- usercustomize
- runtime_settings_mask, imported by usercustomize

It catches environment-specific failures such as running with ``python -S``, a
working directory outside the repository, or a Python configuration that does not
load user customization hooks.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]

PROBE_CODE = r'''
import json
import os
import sys

modules = {
    name: (name in sys.modules)
    for name in (
        "sitecustomize",
        "runtime_security",
        "usercustomize",
        "runtime_settings_mask",
    )
}

payload = {
    "cwd": os.getcwd(),
    "sys_path_0": sys.path[0] if sys.path else "",
    "modules": modules,
    "disable_flag": os.environ.get("PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES", ""),
    "user_site_disabled": bool(getattr(sys, "flags", None) and getattr(sys.flags, "no_user_site", 0)),
}
print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
'''


def fail(message: str, details: Any | None = None) -> int:
    print(f"FAIL {message}")
    if details is not None:
        print(json.dumps(details, ensure_ascii=False, indent=2, sort_keys=True))
    return 1


def main() -> int:
    env = os.environ.copy()
    # The startup hooks are meant to be enabled for this check. If the caller has
    # disabled them globally, report that explicitly instead of silently passing.
    if env.get("PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES"):
        return fail("PPT_STUDIO_DISABLE_RUNTIME_HOTFIXES is set; startup hooks are intentionally disabled")

    result = subprocess.run(
        [sys.executable, "-c", PROBE_CODE],
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    if result.returncode != 0:
        return fail(
            "child Python startup probe failed",
            {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr},
        )

    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except Exception as exc:
        return fail(
            f"could not parse startup probe JSON: {type(exc).__name__}: {exc}",
            {"stdout": result.stdout, "stderr": result.stderr},
        )

    modules = payload.get("modules") or {}
    required = ("sitecustomize", "runtime_security", "usercustomize", "runtime_settings_mask")
    missing = [name for name in required if modules.get(name) is not True]
    if missing:
        return fail(
            "Python startup did not import all expected runtime hook modules",
            {"missing": missing, "probe": payload, "stderr": result.stderr},
        )

    print("OK Python startup hook self-check passed.")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
