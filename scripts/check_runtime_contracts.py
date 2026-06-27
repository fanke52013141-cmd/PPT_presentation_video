#!/usr/bin/env python3
"""Run all lightweight runtime contract checks.

This is a local operator-friendly aggregator. It does not start the full server
and does not call external APIs.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHECKS = [
    ("runtime bootstrap", "scripts.check_runtime_bootstrap_contract", []),
    ("runtime UI injection", "scripts.check_runtime_ui_injection_contract", []),
    ("static extension references", "scripts.check_static_extension_references", []),
    ("runtime bridge installer audit", "scripts.audit_runtime_bridge_installers", []),
]


def main() -> int:
    failures = []
    for label, module_name, argv in CHECKS:
        try:
            module = importlib.import_module(module_name)
            exit_code = module.main(argv) if argv else module.main()
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
        except Exception as exc:
            print(f"FAIL {label}: {type(exc).__name__}: {exc}")
            failures.append(label)
            continue
        if exit_code not in (None, 0):
            print(f"FAIL {label}: exit code {exit_code}")
            failures.append(label)
        else:
            print(f"PASS {label}")
    if failures:
        print("FAIL runtime contract checks failed: " + ", ".join(failures))
        return 1
    print("OK all runtime contract checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
