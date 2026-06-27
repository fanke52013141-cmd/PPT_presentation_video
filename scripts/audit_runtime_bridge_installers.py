#!/usr/bin/env python3
"""Audit runtime bridge installer loops.

Many additive runtime bridges install themselves through a background
``_install_when_ready`` worker. This audit reports bridges that do not expose an
explicit disable environment variable or timeout constant, so long-running local
startup issues are easier to identify.

This is advisory by default: it returns 0 and prints WARN lines. Use ``--strict``
to fail on findings.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_GLOB = "runtime_*.py"


INSTALLER_PATTERN = re.compile(r"def\s+_install_when_ready\s*\(")
TIMEOUT_PATTERN = re.compile(r"INSTALL_TIMEOUT_SEC|time\.monotonic\(\)\s*-\s*started_at|timeout", re.I)
DISABLE_ENV_PATTERN = re.compile(r"PPT_STUDIO_DISABLE_[A-Z0-9_]+")
THREAD_PATTERN = re.compile(r"threading\.Thread\(")


class Finding:
    def __init__(self, path: Path, issue: str) -> None:
        self.path = path
        self.issue = issue

    def __str__(self) -> str:
        return f"{self.path.relative_to(ROOT).as_posix()}: {self.issue}"


def _audit_file(path: Path) -> list[Finding]:
    content = path.read_text(encoding="utf-8")
    if not INSTALLER_PATTERN.search(content):
        return []
    findings: list[Finding] = []
    if THREAD_PATTERN.search(content) and not TIMEOUT_PATTERN.search(content):
        findings.append(Finding(path, "background installer has no explicit timeout"))
    if not DISABLE_ENV_PATTERN.search(content):
        findings.append(Finding(path, "installer has no PPT_STUDIO_DISABLE_* escape hatch"))
    return findings


def audit() -> list[Finding]:
    findings: list[Finding] = []
    for path in sorted(ROOT.glob(RUNTIME_GLOB)):
        findings.extend(_audit_file(path))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit runtime bridge background installers for timeout and disable-env guards.")
    parser.add_argument("--strict", action="store_true", help="Return non-zero when findings exist")
    args = parser.parse_args(argv)

    findings = audit()
    if findings:
        for finding in findings:
            print(f"WARN {finding}")
        if args.strict:
            return 1
    else:
        print("OK runtime bridge installers have timeout/disable guards.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
